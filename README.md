# MSMA Advocacy Maps

Public website from the Missouri State Medical Association showing every Missouri House and Senate district for the 2027 session: who represents it, party, new or incumbent, leadership roles, counties served, Capitol office, committees and filed bills.

**Setting this up for the first time?** Open **START-HERE.html** (download it and open it in your web browser) and follow the steps.

## What's in this folder

| Folder / file | What it is |
|---|---|
| `site/` | The website itself (Home, Interactive Map, Member Roster, Leadership, Committees). |
| `site/assets/legislators.js` | The MSMA member roster: names, party, (I)/(N), leadership, counties. Edit this to correct a member. |
| `site/data/live.json` | Office, phone, email, committees and filed bills. **Filled in automatically every night. Don't edit by hand.** |
| `site/assets/MSMA-Legislator-Contact-Directory-2027.xlsx` | Downloadable contact directory, rebuilt automatically. |
| `updater/update_live.py` | The nightly program that reads official Missouri House and Senate sources. |
| `updater/test_update_live.py` | Offline test for the updater. |
| `.github/workflows/update-and-publish.yml` | Tells GitHub to run the update every night and publish the site. |

## Where the information comes from

- **House:** Missouri House of Representatives XML exports (documents.house.mo.gov), checked once a day.
- **Senate:** Open States API (data from senate.mo.gov), if an `OPENSTATES_API_KEY` secret is set.
- **Safety rule:** details are attached to a district only when the official record's last name matches the MSMA roster, so outgoing legislators' information is never shown under a newly elected member.

Questions: advocacy@msma.org
