#!/usr/bin/env python3
"""
MSMA Advocacy Maps - nightly data updater.

Reads the roster in site/assets/legislators.js (the members MSMA tracks) and
adds "live" details from official sources:

  House  - Missouri House of Representatives XML exports (documents.house.mo.gov):
           Capitol office, phone, email, committees + position, sponsored bills.
  Senate - Open States API v3 (pulls from the Missouri Senate website), if an
           OPENSTATES_API_KEY is set: office, phone, email, sponsored bills,
           committees (when available).

Writes site/data/live.json and regenerates the downloadable contact directory
(site/assets/MSMA-Legislator-Contact-Directory-2027.xlsx).

Safety rule: details are attached to a district ONLY if the official record's
last name matches the member on the MSMA roster. Until newly elected members are
sworn in (January 2027), official records still show outgoing legislators; those
are skipped instead of being shown under the wrong person.

The script never deletes good data because of a temporary outage: if a source
fails, the previous values for that chamber are kept and the error is recorded
in live.json -> "status".

Standard library only, plus openpyxl for the Excel directory.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ROSTER_JS = SITE / "assets" / "legislators.js"
LIVE_JSON = SITE / "data" / "live.json"
STATUS_JSON = SITE / "data" / "status.json"   # refreshed every run, published but not committed
DIRECTORY_XLSX = SITE / "assets" / "MSMA-Legislator-Contact-Directory-2027.xlsx"

SESSION_YEAR = os.environ.get("SESSION_YEAR", "2027")          # legislative year
OPENSTATES_SESSION = os.environ.get("OPENSTATES_SESSION", SESSION_YEAR)
OPENSTATES_KEY = os.environ.get("OPENSTATES_API_KEY", "").strip()
HOUSE_XML_INDEX = "https://documents.house.mo.gov/"
HOUSE_MEMBERLIST_CANDIDATES = [  # tried after link discovery on the index page
    "https://documents.house.mo.gov/xml/MemberList.xml",
    "https://documents.house.mo.gov/MemberList.xml",
]
USER_AGENT = "MSMA-Advocacy-Maps-updater/1.0 (+advocacy@msma.org)"
PAUSE = float(os.environ.get("REQUEST_PAUSE", "0.6"))  # be polite to state servers


# ----------------------------------------------------------------- helpers
def log(*a):
    print(*a, flush=True)


def fetch(url: str, headers: dict | None = None, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            time.sleep(PAUSE)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # network hiccup: retry
            last = e
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())


def last_name(full: str) -> str:
    parts = [p for p in re.split(r"[\s,]+", (full or "").strip()) if p]
    parts = [p for p in parts if norm(p) not in {"jr", "sr", "ii", "iii", "iv", "rep", "sen", "dr"}]
    return parts[-1] if parts else ""


def same_person(roster_name: str, official_last: str, official_full: str = "") -> bool:
    """Last names must match (allowing hyphenated/compound names and small typos)."""
    a = norm(last_name(roster_name))
    candidates = {norm(official_last)} | {norm(x) for x in re.split(r"[\s-]+", official_last or "")}
    if official_full:
        candidates.add(norm(last_name(official_full)))
    candidates.discard("")
    if not a or not candidates:
        return False
    if a in candidates:
        return True
    # roster may hold a hyphenated name ("Tyson-Smith") and the record only part of it
    for piece in re.split(r"[\s-]+", last_name(roster_name)):
        if norm(piece) in candidates and len(norm(piece)) > 2:
            return True
    # tolerate one-letter spelling differences (e.g. Stienhoff / Steinhoff)
    import difflib
    return any(difflib.SequenceMatcher(None, a, c).ratio() >= 0.85 for c in candidates)


def load_roster() -> dict:
    txt = ROSTER_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.LEG\s*=\s*(\{.*\})\s*;?\s*$", txt, re.S)
    if not m:
        raise SystemExit("Could not read site/assets/legislators.js")
    return json.loads(m.group(1))


def load_previous() -> dict:
    try:
        return json.loads(LIVE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(el, name: str) -> str:
    for c in el.iter():
        if local(c.tag) == name:
            return html.unescape((c.text or "").strip())
    return ""


def children(el, name: str):
    return [c for c in el.iter() if local(c.tag) == name]


def house_bill_url(bill_type: str, number: str) -> str:
    code = f"{bill_type}{number}".replace(" ", "")
    return f"https://house.mo.gov/Bill.aspx?bill={urllib.parse.quote(code)}&year={SESSION_YEAR}&code=R"


def house_member_url(district: int) -> str:
    return f"https://house.mo.gov/MemberDetails.aspx?district={district:03d}"


def senate_member_url(district: int) -> str:
    return f"https://www.senate.mo.gov/DistrictWebApplication/Contact?DistrictNumber={district}"


# ------------------------------------------------------------------- House
def find_house_memberlist() -> str:
    reason = ""
    try:
        page = fetch(HOUSE_XML_INDEX).decode("utf-8", "replace")
        for href in re.findall(r'href=["\']([^"\']+\.xml)["\']', page, re.I):
            if "memberlist" in href.lower():
                return urllib.parse.urljoin(HOUSE_XML_INDEX, href)
    except Exception as e:
        reason = str(e)
        log("  (could not read House XML index page:", e, ")")
    for url in HOUSE_MEMBERLIST_CANDIDATES:
        try:
            fetch(url)
            return url
        except Exception:
            continue
    raise RuntimeError("Could not locate the House MemberList.xml file" + (f" ({reason})" if reason else ""))


def parse_house_member(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    info = next((e for e in root.iter() if local(e.tag) == "RepresentativeInfo"), root)
    committees = []
    for c in children(info, "Committee"):
        name = child_text(c, "CommitteeName")
        if name:
            committees.append({"name": name, "position": child_text(c, "CommitteePosition") or "Member"})
    bills, seen = [], set()
    for b in children(root, "SponsoredBill"):
        btype, num = child_text(b, "BillType"), child_text(b, "BillNumber")
        if not (btype and num):
            continue
        ident = f"{btype} {num}"
        if ident in seen:
            continue
        seen.add(ident)
        bills.append({"id": ident, "title": child_text(b, "LongTitle"), "url": house_bill_url(btype, num)})
    cosponsored = len({(child_text(b, "BillType"), child_text(b, "BillNumber")) for b in children(root, "CoSponsoredBill")})
    first, last = child_text(info, "FirstName"), child_text(info, "LastName")
    return {
        "official_name": f"{first} {last}".strip(),
        "last_name": last,
        "district": child_text(info, "DistrictNum"),
        "office": re.sub(r"\s+", " ", child_text(info, "CapitolAddress")),
        "phone": child_text(info, "PhoneNumber"),
        "email": child_text(info, "EmailAddress"),
        "photo": child_text(info, "PhotoLink"),
        "committees": committees,
        "bills": bills,
        "cosponsored": cosponsored,
    }


def update_house(roster: dict) -> tuple[dict, dict]:
    url = find_house_memberlist()
    log("House member list:", url)
    root = ET.fromstring(fetch(url))
    links = {}
    for item in root.iter():
        if local(item.tag) == "RepresentativeXML":
            d, link = child_text(item, "RepresentativeDistrict"), child_text(item, "RepresentativeXMLLink")
            if d.isdigit() and link:
                links[int(d)] = urllib.parse.urljoin(url, link)
    if not links:
        raise RuntimeError("House MemberList.xml had no RepresentativeXML entries")
    out, waiting = {}, []
    for district in sorted(links):
        member = roster["house"].get(str(district))
        if not member:
            continue
        try:
            rec = parse_house_member(fetch(links[district]))
        except Exception as e:
            log(f"  House {district}: {e}")
            continue
        if not same_person(member["name"], rec["last_name"], rec["official_name"]):
            waiting.append(district)
            continue
        rec.pop("last_name", None)
        rec["page"] = house_member_url(district)
        out[str(district)] = rec
    log(f"  House: {len(out)} matched, {len(waiting)} waiting for new-member records")
    return out, {"matched": len(out), "waiting": waiting}


# ------------------------------------------------------------------ Senate
def os_get(path: str, params: list[tuple[str, str]]) -> dict:
    q = urllib.parse.urlencode(params)
    data = fetch(f"https://v3.openstates.org{path}?{q}", headers={"X-API-KEY": OPENSTATES_KEY, "Accept": "application/json"})
    return json.loads(data)


def os_paged(path: str, params: list[tuple[str, str]], max_pages: int = 25):
    page = 1
    while page <= max_pages:
        res = os_get(path, params + [("page", str(page))])
        for r in res.get("results", []):
            yield r
        pg = res.get("pagination", {})
        if page >= int(pg.get("max_page", 1) or 1):
            break
        page += 1


def update_senate(roster: dict) -> tuple[dict, dict]:
    if not OPENSTATES_KEY:
        raise RuntimeError("No OPENSTATES_API_KEY set - Senate details skipped (see START-HERE guide, step 6)")
    people = list(os_paged("/people", [("jurisdiction", "mo"), ("org_classification", "upper"),
                                         ("include", "offices"), ("per_page", "50")], max_pages=3))
    by_district = {}
    for p in people:
        d = str((p.get("current_role") or {}).get("district") or "").strip()
        if d.isdigit():
            by_district[int(d)] = p
    committees_by_person: dict[str, list] = {}
    try:
        for c in os_paged("/committees", [("jurisdiction", "mo"), ("chamber", "upper"),
                                            ("include", "memberships"), ("per_page", "20")], max_pages=10):
            for mem in c.get("memberships", []) or []:
                pid = (mem.get("person") or {}).get("id") or mem.get("person_id")
                if pid:
                    committees_by_person.setdefault(pid, []).append(
                        {"name": c.get("name", ""), "position": (mem.get("role") or "member").title()})
    except Exception as e:
        log("  Senate committees not available from Open States yet:", e)
    out, waiting = {}, []
    for district, member in ((int(k), v) for k, v in roster["senate"].items()):
        p = by_district.get(district)
        if not p or not same_person(member["name"], p.get("family_name") or last_name(p.get("name", "")), p.get("name", "")):
            waiting.append(district)
            continue
        office = next((o for o in p.get("offices", []) or [] if (o.get("classification") or "").lower() == "capitol"),
                      (p.get("offices") or [{}])[0] if p.get("offices") else {})
        bills = []
        try:
            for b in os_paged("/bills", [("jurisdiction", "mo"), ("session", OPENSTATES_SESSION),
                                          ("sponsor", p["id"]), ("sponsor_classification", "primary"),
                                          ("include", "sources"), ("sort", "first_action_asc"), ("per_page", "20")], max_pages=10):
                src = next((s.get("url") for s in b.get("sources", []) or [] if "senate.mo.gov" in (s.get("url") or "")), None)
                bills.append({"id": b.get("identifier", ""), "title": b.get("title", ""),
                              "url": src or b.get("openstates_url", "")})
        except Exception as e:
            log(f"  Senate {district} bills: {e}")
        out[str(district)] = {
            "official_name": p.get("name", ""),
            "district": str(district),
            "office": re.sub(r"\s+", " ", office.get("address") or ""),
            "phone": office.get("voice") or "",
            "email": p.get("email") or "",
            "photo": p.get("image") or "",
            "committees": committees_by_person.get(p["id"], []),
            "bills": bills,
            "cosponsored": None,
            "page": senate_member_url(district),
        }
    log(f"  Senate: {len(out)} matched, {len(waiting)} waiting")
    return out, {"matched": len(out), "waiting": waiting}


# --------------------------------------------------------------- directory
def build_directory(roster: dict, live: dict) -> None:
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    except ImportError:
        log("openpyxl not installed - contact directory not rebuilt")
        return
    F = "Arial"
    thin = Side(style="thin", color="BFBFBF")
    B = Border(left=thin, right=thin, top=thin, bottom=thin)
    party_color = {"R": "B71C1C", "D": "1A4F9C"}
    wb = openpyxl.Workbook()
    stamp = live.get("updated_display") or "not yet available"
    for i, ch in enumerate(["senate", "house"]):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = "Senate" if ch == "senate" else "House"
        ws.sheet_view.showGridLines = False
        title = "Missouri Senate" if ch == "senate" else "Missouri House of Representatives"
        ws["A1"] = f"{title} - {SESSION_YEAR} Legislator Contact Directory"
        ws["A1"].font = Font(name=F, size=15, bold=True, color="1F3468")
        ws["A2"] = (f"MSMA Advocacy Maps - office, phone, email and committees update automatically from official sources "
                    f"(last update: {stamp}). Blank cells fill in once the {SESSION_YEAR} session information is published. "
                    "Questions: advocacy@msma.org")
        ws["A2"].font = Font(name=F, size=9, italic=True, color="555555")
        hdr = ["District #", "Name", "Party", "Status", "Leadership position", "Counties served",
               "Capitol office", "Phone", "Email", "Committees", "Bills filed", "Official page"]
        for c, h in enumerate(hdr, 1):
            x = ws.cell(4, c, h)
            x.font = Font(name=F, bold=True, color="FFFFFF")
            x.fill = PatternFill("solid", fgColor="1F3468")
            x.border = B
            x.alignment = Alignment(vertical="center", wrap_text=True)
        r = 5
        for did, m in sorted(roster[ch].items(), key=lambda kv: int(kv[0])):
            lv = (live.get(ch) or {}).get(did, {})
            url = house_member_url(int(did)) if ch == "house" else senate_member_url(int(did))
            comm = "; ".join(f"{c['name']}" + (f" ({c['position']})" if c.get("position") and c["position"].lower() != "member" else "")
                             for c in lv.get("committees", []))
            vals = [int(did), ("Rep. " if ch == "house" else "Sen. ") + m["name"],
                    "Republican" if m["party"] == "R" else "Democrat",
                    "Incumbent (I)" if m["status"] == "I" else "Newly elected (N)",
                    m.get("role") or "", m.get("counties", ""), lv.get("office", ""), lv.get("phone", ""),
                    lv.get("email", ""), comm, len(lv.get("bills", [])) if lv else "", "Official page"]
            for c, v in enumerate(vals, 1):
                x = ws.cell(r, c, v)
                x.font = Font(name=F, size=10, bold=(c == 2))
                x.border = B
                x.alignment = Alignment(vertical="top", wrap_text=c in (6, 7, 10), horizontal="center" if c in (1, 11) else "left")
            ws.cell(r, 3).font = Font(name=F, size=10, bold=True, color=party_color[m["party"]])
            if lv.get("email"):
                ws.cell(r, 9).hyperlink = f"mailto:{lv['email']}"
                ws.cell(r, 9).font = Font(name=F, size=10, color="0563C1", underline="single")
            link = ws.cell(r, 12)
            link.hyperlink = url
            link.font = Font(name=F, size=10, color="0563C1", underline="single")
            r += 1
        for col, w in zip("ABCDEFGHIJKL", [10, 28, 12, 17, 26, 40, 26, 16, 30, 44, 10, 15]):
            ws.column_dimensions[col].width = w
        ws.freeze_panes = "C5"
        ws.auto_filter.ref = f"A4:L{r - 1}"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "4:4"
    DIRECTORY_XLSX.parent.mkdir(parents=True, exist_ok=True)
    wb.save(DIRECTORY_XLSX)
    log("Contact directory rebuilt:", DIRECTORY_XLSX.name)


# -------------------------------------------------------------------- main
def main() -> int:
    roster = load_roster()
    prev = load_previous()
    now = dt.datetime.now(dt.timezone.utc)
    central = now.astimezone(dt.timezone(dt.timedelta(hours=-6)))
    live = {"session": SESSION_YEAR, "house": prev.get("house", {}), "senate": prev.get("senate", {}),
            "updated": prev.get("updated"), "updated_display": prev.get("updated_display")}
    status = {"checked": now.isoformat(timespec="seconds"), "checked_display": central.strftime("%b %d, %Y %I:%M %p CT")}
    for chamber, fn in (("house", update_house), ("senate", update_senate)):
        log(f"Updating {chamber}...")
        try:
            data, info = fn(roster)
            if data or not live[chamber]:
                live[chamber] = data
            status[chamber] = {"ok": True, **info}
        except Exception as e:
            log(f"  {chamber} not updated (previous data kept): {e}")
            status[chamber] = {"ok": False, "error": str(e)[:300], "matched": len(live[chamber])}
    before = json.dumps({k: prev.get(k) for k in ("house", "senate")}, sort_keys=True)
    after = json.dumps({k: live.get(k) for k in ("house", "senate")}, sort_keys=True)
    changed = after != before or not LIVE_JSON.exists()
    if changed:
        live["updated"] = now.isoformat(timespec="seconds")
        live["updated_display"] = central.strftime("%b %d, %Y").replace(" 0", " ")
        LIVE_JSON.parent.mkdir(parents=True, exist_ok=True)
        LIVE_JSON.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
        log("Member details changed - live.json saved.")
    else:
        log("No changes to member details.")
    STATUS_JSON.parent.mkdir(parents=True, exist_ok=True)
    STATUS_JSON.write_text(json.dumps(status, indent=1), encoding="utf-8")
    if changed or not DIRECTORY_XLSX.exists():
        build_directory(roster, live)
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
