"""
Offline test for update_live.py - run with:  python updater/test_update_live.py

Simulates the Missouri House XML exports (structure from
documents.house.mo.gov/XMLMemberExports.html) and the Open States API, then
checks the output. No internet needed. Works on a temporary copy of site/.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

INDEX_HTML = b'<html><a href="xml/MemberList.xml">MemberList.xml</a></html>'
MEMBERLIST = b"""<?xml version="1.0"?>
<RepresentativeList>
 <RepresentativeXML><RepresentativeDistrict>12</RepresentativeDistrict>
  <RepresentativeXMLLink>https://documents.house.mo.gov/xml/rep012.xml</RepresentativeXMLLink><LastTimeRun>01-09-2027 10:00:00.000</LastTimeRun></RepresentativeXML>
 <RepresentativeXML><RepresentativeDistrict>134</RepresentativeDistrict>
  <RepresentativeXMLLink>https://documents.house.mo.gov/xml/rep134.xml</RepresentativeXMLLink><LastTimeRun>01-09-2027 10:00:00.000</LastTimeRun></RepresentativeXML>
 <RepresentativeXML><RepresentativeDistrict>45</RepresentativeDistrict>
  <RepresentativeXMLLink>https://documents.house.mo.gov/xml/rep045.xml</RepresentativeXMLLink><LastTimeRun>01-09-2027 10:00:00.000</LastTimeRun></RepresentativeXML>
</RepresentativeList>"""
REP = """<?xml version="1.0"?><RepresentativeData><RepresentativeInfo>
 <PhotoLink>https://house.mo.gov/photo.jpg</PhotoLink><LastName>{last}</LastName><FirstName>{first}</FirstName>
 <DistrictNum>{d}</DistrictNum><Party>{p}</Party><Counties><County><CountyName>Greene</CountyName></County></Counties>
 <Committees>{comm}</Committees>
 <CapitolAddress>201 West Capitol Avenue, Room 308-A, Jefferson City MO 65101</CapitolAddress>
 <PhoneNumber>573-751-0000</PhoneNumber><EmailAddress>{first}.{last}@house.mo.gov</EmailAddress></RepresentativeInfo>
 <RepresentativeLegislation>{bills}<CoSponsoredBill><BillType>HB</BillType><BillNumber>9</BillNumber><LegislationType>Co-sponsor</LegislationType></CoSponsoredBill></RepresentativeLegislation>
</RepresentativeData>"""
C = "<Committee><CommitteeName>{n}</CommitteeName><CommitteePosition>{pos}</CommitteePosition></Committee>"
SB = "<SponsoredBill><BillType>HB</BillType><BillNumber>{n}</BillNumber><LegislationType>Sponsor</LegislationType><LongTitle>{t}</LongTitle></SponsoredBill>"

FILES = {
    "https://documents.house.mo.gov/": INDEX_HTML,
    "https://documents.house.mo.gov/xml/MemberList.xml": MEMBERLIST,
    # District 12: roster has newly elected Tracey Steele; official file still shows outgoing member -> must be skipped
    "https://documents.house.mo.gov/xml/rep012.xml": REP.format(last="Hickey", first="Jerry", d=12, p="R", comm="", bills="").encode(),
    # District 134: Alex Riley, matches
    "https://documents.house.mo.gov/xml/rep134.xml": REP.format(
        last="Riley", first="Alex", d=134, p="R",
        comm=C.format(n="Rules - Administrative Oversight", pos="Chair") + C.format(n="Health and Mental Health", pos="Member"),
        bills=SB.format(n=101, t="Modifies provisions relating to physician licensure") + SB.format(n=102, t="Telehealth parity")).encode(),
    # District 45: roster spells it "Kathy Stienhoff"; official "Steinhoff" -> tolerated typo, matches
    "https://documents.house.mo.gov/xml/rep045.xml": REP.format(last="Steinhoff", first="Kathy", d=45, p="D",
        comm=C.format(n="Elementary and Secondary Education", pos="Ranking Minority Member"), bills="").encode(),
}

OS_PEOPLE = {"results": [
    {"id": "ocd-person/aaa", "name": "Stephen Webber", "family_name": "Webber", "email": "Stephen.Webber@senate.mo.gov",
     "current_role": {"district": "19"}, "offices": [{"classification": "capitol", "address": "201 W Capitol Ave Rm 329", "voice": "573-751-3931"}]},
    {"id": "ocd-person/bbb", "name": "Karla May", "family_name": "May", "current_role": {"district": "4"}, "offices": []},
], "pagination": {"max_page": 1}}
OS_COMMITTEES = {"results": [{"name": "Health and Welfare", "memberships": [{"person": {"id": "ocd-person/aaa"}, "role": "member"}]}],
                 "pagination": {"max_page": 1}}
OS_BILLS = {"results": [{"identifier": "SB 12", "title": "Modifies provisions relating to health care",
                         "sources": [{"url": "https://www.senate.mo.gov/27info/BTS_Web/Bill.aspx?SessionType=R&BillID=1"}]}],
            "pagination": {"max_page": 1}}


def fake_fetch(url, headers=None, timeout=45):
    if url in FILES:
        return FILES[url]
    if url.startswith("https://v3.openstates.org/people"):
        return json.dumps(OS_PEOPLE).encode()
    if url.startswith("https://v3.openstates.org/committees"):
        return json.dumps(OS_COMMITTEES).encode()
    if url.startswith("https://v3.openstates.org/bills"):
        return json.dumps(OS_BILLS if "aaa" in url else {"results": [], "pagination": {"max_page": 1}}).encode()
    raise RuntimeError(f"unexpected URL {url}")


def run():
    import update_live as U
    tmp = Path(tempfile.mkdtemp())
    site = tmp / "site"
    shutil.copytree(HERE.parent / "site" / "assets", site / "assets")
    (site / "data").mkdir()
    U.SITE, U.ROSTER_JS = site, site / "assets" / "legislators.js"
    U.LIVE_JSON, U.STATUS_JSON = site / "data" / "live.json", site / "data" / "status.json"
    U.DIRECTORY_XLSX = site / "assets" / "dir.xlsx"
    U.fetch, U.PAUSE, U.OPENSTATES_KEY = fake_fetch, 0, "test-key"

    U.main()
    live = json.loads(U.LIVE_JSON.read_text())
    status = json.loads(U.STATUS_JSON.read_text())
    assert "12" not in live["house"], "outgoing member must not be attached to a new member"
    assert 12 in status["house"]["waiting"]
    r = live["house"]["134"]
    assert r["committees"][0] == {"name": "Rules - Administrative Oversight", "position": "Chair"}
    assert [b["id"] for b in r["bills"]] == ["HB 101", "HB 102"]
    assert r["bills"][0]["url"] == "https://house.mo.gov/Bill.aspx?bill=HB101&year=2027&code=R"
    assert r["office"].startswith("201 West Capitol Avenue, Room 308-A") and r["cosponsored"] == 1
    assert "45" in live["house"], "one-letter spelling difference should still match"
    s = live["senate"]["19"]
    assert s["committees"][0]["name"] == "Health and Welfare" and s["bills"][0]["id"] == "SB 12"
    assert s["phone"] == "573-751-3931" and "senate.mo.gov" in s["bills"][0]["url"]
    assert "4" not in live["senate"], "outgoing senator (Karla May) must not be attached to Gina Mitten"
    assert U.DIRECTORY_XLSX.exists()
    import openpyxl
    ws = openpyxl.load_workbook(U.DIRECTORY_XLSX)["House"]
    row = next(r for r in ws.iter_rows(min_row=5, values_only=True) if r[0] == 134)
    assert row[7] == "573-751-0000" and "Rules - Administrative Oversight (Chair)" in row[9] and row[10] == 2

    # House returns a web page instead of XML -> clear error that shows what was sent
    def html_page(url, headers=None, timeout=45):
        if "documents.house.mo.gov" in url:
            return b"<!DOCTYPE html><html><head><title>Access Denied</title></head><body>blocked</body></html>"
        return fake_fetch(url, headers, timeout)
    U.fetch = html_page
    U.main()
    st = json.loads(U.STATUS_JSON.read_text())
    assert st["house"]["ok"] is False and "Access Denied" in st["house"]["error"], st["house"]
    assert json.loads(U.LIVE_JSON.read_text())["house"]["134"]["bills"], "data kept"
    U.fetch = fake_fetch
    assert U.house_session_codes() == ["271", "261"]

    # Second run: House source down -> previous House data must be kept, status shows the error
    def broken(url, headers=None, timeout=45):
        if "house.mo.gov" in url:
            raise RuntimeError("simulated outage")
        return fake_fetch(url, headers, timeout)
    U.fetch = broken
    U.HOUSE_MEMBERLIST_CANDIDATES = []
    U.main()
    live2 = json.loads(U.LIVE_JSON.read_text())
    status2 = json.loads(U.STATUS_JSON.read_text())
    assert live2["house"]["134"]["bills"], "data must survive a source outage"
    assert status2["house"]["ok"] is False and "outage" in status2["house"]["error"]

    # Third run: no Open States key -> Senate skipped, previous Senate data kept
    U.fetch, U.OPENSTATES_KEY = fake_fetch, ""
    U.main()
    live3 = json.loads(U.LIVE_JSON.read_text())
    assert live3["senate"]["19"]["bills"] and json.loads(U.STATUS_JSON.read_text())["senate"]["ok"] is False
    shutil.rmtree(tmp)
    print("All updater tests passed.")


if __name__ == "__main__":
    run()
