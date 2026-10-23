SYNTHETIC SAMPLE LISTS - NOT REAL SANCTIONS DATA.

These files mimic the structure of the official list files so the screening code, tests and the console demo work
offline. Every name, date and identifier here is invented. For real screening the owner downloads the official
files with `python tools/fetch_sanctions_lists.py` (writes var/sanctions/ + manifest.json) and loads them with
`atlas-payments sanctions-load var/sanctions`.

* sema-lmes.sample.xml    -> shape of Global Affairs Canada sema-lmes.xml (<data-set><record>)
* un-consolidated.sample.xml -> shape of https://scsanctions.un.org/resources/xml/en/consolidated.xml
* ofac-sdn.sample.xml     -> shape of https://sanctionslistservice.ofac.treas.gov/api/download/sdn.xml
