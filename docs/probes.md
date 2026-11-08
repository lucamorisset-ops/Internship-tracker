# Relevés réels des sites (08/11/2026)

Captured from a real browser on 08/11/2026. The HTML below is *cleaned*
(scripts, images and most attributes removed, whitespace collapsed) but tag
names, classes, hrefs and text are real. Build test fixtures from these
snippets: wrap 2–3 cards in the parent element shown, vary titles/dates.

For each source: URL read, robots.txt, whether offers are in the raw HTML
("raw" = plain HTTP GET is enough) or only after JavaScript ("live").

---------------------------------------------------------------------------
## oracle_hcm — Lazard (icbpjb), JP Morgan (jpmc), Edmond de Rothschild (evht)

API (public, used by the official portal itself):
`{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},facetsList=NONE,limit=25,offset=0,sortBy=POSTING_DATES_DESC[,keyword=%22off-cycle%22][,selectedLocationsFacet=ID1%3BID2][,selectedFlexFieldsFacets=%22AttributeChar8%7CAsset%20Management%3BCorporate%22]`

Response: `{"items":[{"TotalJobsCount":165,"Offset":0,"Limit":25, ..., "requisitionList":[...]}],"hasMore":false,...}`
`hasMore` at top level is about `items`, not jobs: page with `offset` while
`offset + len(requisitionList) < TotalJobsCount` (cap 200 jobs).

requisitionList item (real, JPM):
```json
{"Id":"210802419","Title":"2027 Commercial & Investment Banking - Sales - Off-cycle Internship - Paris",
 "PostedDate":"2026-10-22","PostingEndDate":null,"PrimaryLocation":"Paris, France",
 "PrimaryLocationCountry":"FR","ShortDescriptionStr":"...","JobFamily":"...","JobFunction":"...",
 "ContractType":null,"JobType":null,"WorkerType":null,"StudyLevel":null,
 "secondaryLocations":[{"CountryCode":"US","Name":"New York, NY, United States"}]}
```
Offer page URL: `{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{Id}` (JavaScript page:
detail must come from the API, e.g.
`/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id=%22{Id}%22,siteNumber={site}`
-> `items[0].ExternalDescriptionStr` (HTML) and `ExternalResponsibilitiesStr`, `ExternalQualificationsStr`).

* Lazard: host `https://icbpjb.fa.ocs.oraclecloud.com`, site `LazardStudentCareers`, robots.txt 404 (allowed).
  121 jobs total on the student site. Official link filters: selectedFlexFieldsFacets
  `"AttributeChar8|Asset Management;Corporate"`, selectedLocationsFacet `300000000798421;300000000798256;300000000798598`
  (Paris, Lyon, Nantes). Real titles: "Stage H/F - Analyste Actions – Janvier 2027" (Id 6313, PostedDate 2026-06-30),
  "Stage H/F - Assistant de Gestion Fixed Income – Janvier 2027" (6316), "Stage H/F - Assistant Gestion de Portefeuilles Obligataires" (6687, 2026-10-02).
* JP Morgan: host `https://jpmc.fa.oraclecloud.com`, site `CX_1001`, robots.txt answers 403 (RFC 9309: allowed).
  7110 jobs worldwide. Location facet ids: France `300000000289270`, United Kingdom `300000000289276`.
  keyword "internship" + FR/UK = 34 jobs, keyword "off-cycle" + FR/UK = 23 jobs (many are not internships:
  matching sorts that out). Real: 210802076 "2027 Commercial & Investment Banking - Global Markets - Off-cycle Internship – Paris" (2026-10-22, FR);
  210780537 "2027 – Sales – Summer Internship - Paris" (FR); 210807156 "Vice President - Asset Managers & Funds Credit Risk" (GB).
* Edmond de Rothschild: host `https://evht.fa.ocs.oraclecloud.eu`, site `CX_7001`, robots.txt 404. 24 jobs, 9 in France.
  Real: 2955 "Stagiaire RH - Administration, Compensation & Benefits" (Luxembourg). Most EdR internships are only
  on JobTeaser (not read: terms of use) -> result status "partiel" with that explanation.

---------------------------------------------------------------------------
## smartrecruiters — Sycomore
API: `https://api.smartrecruiters.com/v1/companies/SycomoreAssetManagement/postings?limit=100&offset=0`
Standard SmartRecruiters Posting API: `{"offset":0,"limit":100,"totalFound":7,"content":[{"id":"744000154486600",
"name":"Stage 6 mois – Analyste Crédit","releasedDate":"2026-10-08T09:12:00.000Z",
"location":{"city":"Paris","country":"fr","fullLocation":"Paris, Île-de-France, France"},
"typeOfEmployment":{"id":"intern","label":"Internship"},"company":{"identifier":"SycomoreAssetManagement","name":"Sycomore Asset Management"},
"ref":"https://api.smartrecruiters.com/v1/companies/SycomoreAssetManagement/postings/744000154486600"}]}`
Public offer URL: `https://jobs.smartrecruiters.com/SycomoreAssetManagement/{id}-{slug of name}` (id alone also works).
Detail (enrich): `GET {ref}` -> `jobAd.sections.jobDescription.text`, `postingUrl`.
Other real titles: "Stage Analyste ESG – 6 mois à compter de janvier 2027" (744000154965945),
"Stage Assistant de gestion (Quantitative, Finance, Data & IA) – 6 mois – S1 2027" (744000154970480).

---------------------------------------------------------------------------
## wp_job — Mirova on recrutement.natixis.com (WordPress)
API: `https://recrutement.natixis.com/app/wp-json/wp/v2/job?search=stage&per_page=100&page=1&_fields=id,date,title,link,class_list`
Headers `X-WP-Total: 76`, `X-WP-TotalPages: 1`. robots.txt disallows /lieu/, /location/, /emploi/, /entreprise/,
/emplois/, /category/ — NOT /app/wp-json/ nor /job/.
Item (real):
```json
{"id":20732,"date":"2026-11-06T17:10:14","link":"https://recrutement.natixis.com/job/stage-6-mois-analyste-investissement-f-h/",
 "title":{"rendered":"Stage &#8211; 6 mois &#8211; Analyste Investissement F/H"},
 "class_list":["post-20732","job","type-job","status-publish","hentry","tax_channel-channelnatixis-2","tax_sector-commercial",
 "tax_job-responsable-dinvestissement","tax_brands-mirova","tax_contract-stage","tax_place-ile-de-france","tax_city-paris","tax_country-france"]}
```
Keep only items whose class_list contains `tax_brands-mirova` or `tax_brands-mirova-us` (param `brands`).
Contract from `tax_contract-*`, city from `tax_city-*`, country from `tax_country-*`. ext_id = WP id.
Also read `search=internship` (English offers) and merge.

---------------------------------------------------------------------------
## talentsoft — Amundi
List: `https://jobs.amundi.com/offre-de-emploi/liste-offres.aspx?changefacet=1&facet_JobCountry=79` (France, 60 offers,
50 per page) and `...facet_JobCountry=162` (UK). raw HTML OK. robots.txt empty (allowed).
Pagination: Talentsoft uses `&page=2` (verify: stop when a page brings no new offer; max 4 pages).
Parent `ul.ts-related-offers__row`, card:
```html
<li class="ts-offer-list-item offerlist-item " title=""><h3 class="ts-offer-list-item__title styleh3"><a class="ts-offer-list-item__title-link " href="/offre-de-emploi/emploi-stage-communication-visuelle-formation-en-epargne-salariale-et-retraite-h-f_113340.aspx" title="2026-113340"> Stage - Communication visuelle – Formation en Epargne Salariale et Retraite H/F </a></h3><span class="ts-offer-list-item-favorite-link ..." data-reference="2026-113340"></span><ul class="ts-offer-list-item__description "><li>Stage</li><li>Amundi Asset Management</li><li>France</li><li class="noBorder"> Paris 15 éme </li></ul></li>
```
description li = [contract, entity, country, city]. No date on the list: publication date is on the
offer page (generic enrich). ext_id = number in `_(\d+).aspx`. Real ids: 116937 "Stage - Assistant gestion multi-asset H/F",
117046 "Stage - Assistant spécialiste produit gestions actions H/F".

---------------------------------------------------------------------------
## bnp — BNP Paribas
Lists (contract = Stage is in the URL, so internships_only):
`https://group.bnpparibas/emploi-carriere/toutes-offres-emploi/stage/bnp-paribas-asset-management` (6 offres)
and `/stage/bnp-paribas-corporate-institutional-banking`, `/stage/bnp-paribas-wealth-management`, `/stage/portzamparc`,
plus `https://group.bnpparibas/en/careers/all-job-offers/trainee-internship/bnp-paribas-asset-management`.
raw HTML OK. robots.txt disallows query strings like `*?q`, `*?$`, `*?NumPage*`, `*?field*`… -> never add a query
string; pagination (if any) must be a path, else read page 1 only and set complete=False when the page says more.
Parent `ul.results.rh-results`, card:
```html
<li class="type type-28"><article class="card-custom card-offer category-28"><a href="/emploi-carriere/offre-emploi/praktikum-all-genders-im-bereich-marketing-communication-bei-asset-man" class="card-link"><div class="card-container"><div class="card-flex"><div class="card-content"><div class="offer-type">Stage</div><h3 class="title-4">Praktikum (all genders) im Bereich Marketing &amp; Communication bei Asset Management</h3><div class="offer-location"><span class="icon icon-location"></span> Francfort, Hesse, Allemagne </div></div><div class="offer-logo"></div></div></div></a></article></li>
```
Page text shows "6 offres". ext_id = slug after `/offre-emploi/`. No date on list.

---------------------------------------------------------------------------
## talentbrew — BlackRock (Radancy TalentBrew)
`https://careers.blackrock.com/category/students-and-graduates-jobs/45831/9022304/1` then `/1/2`, `/1/3` (10 per page
in raw HTML). robots.txt: `Disallow:/search-jobs/` only.
Parent `ul.section3__search-results-ul`, card:
```html
<li class="section3__search-results-li"><a class="section3__search-results-a" href="/job/london/2027-full-time-analyst-program-emea/45831/97150826656" data-job-id="97150826656"><h2 class="section3__job-title">2027 Full-Time Analyst Program - EMEA</h2><span class="job-location section3__job-location section3__job-information"><span>Location:</span><span class="section3__job-info">London, England</span></span><span class="job-location section3__job-location section3__job-information"><span>Additional Locations:</span><span class="section3__job-info"> Abu Dhabi, Amsterdam, Belgrade, Brussels, Budapest, Cape Town, Copenhagen, Edinburgh, Frankfurt, London, Luxembourg, Milan, Munich, Paris, Riyadh, Stockholm </span></span><span class="job-category section3__job-category section3__job-information"><span>Team:</span><span class="section3__job-info">STUDENTS AND GRADUATES</span></span></a><button class="js-save-job-btn section3__saved-jobs-button" data-job-id="97150826656" data-org-id="45831"><span class="sr-only">Save for Later</span></button></li>
```
location = main + additional locations. ext_id = data-job-id. Known: 97104654800 "2027 Off-cycle Internship Program – EMEA".
Offer pages carry JSON-LD JobPosting (generic enrich).

---------------------------------------------------------------------------
## talnet — Morgan Stanley campus (Oleeo tal.net)
`https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/jobboard/vacancy/1/adv/` (50 rows) then `?start=50`.
robots.txt: `Disallow: /*/agent/ /*/ats/ /*/channel/`, **Crawl-delay: 10**, and full disallow for ClaudeBot/GPTBot (not us).
Table headers "Title", "City". Parent `tbody`, row:
```html
<tr class="opp_22429 search_res details_row" data-oppid="22429" data-title="2027 Spring Investment Management  Sustainability and  Global Stewardship Co-Op (New York)"><td class="comm_list_tbody"><a class="subject" href="https://morganstanley.tal.net/vx/lang-en-GB/mobile-0/brand-2/candidate/so/pm/1/pl/1/opp/22429-2027-Spring-Investment-Management-Sustainability-and-Global-Stewardship-Co-Op-New-York/en-GB"> 2027 Spring Investment Management Sustainability and Global Stewardship Co-Op (New York) </a></td><td class="comm_list_tbody"> New York </td></tr>
```
ext_id = data-oppid. Known: 22234 "2027 Investment Management Off-cycle Internship – Fixed Income" (London), 22340.
Pagination link `?start=50` present on page 1. Total ~73.

---------------------------------------------------------------------------
## creditmutuel — La Française / Crédit Mutuel AM
`https://recrutement.creditmutuel.fr/fr/nos_offres.html?socs=39%7C4962%7C1499%7C1497%7C4963%7C4965%7C5007%7C5008%7C1496`
raw HTML shows the 15 most recent offers of these entities (complete=False). robots.txt: Allow / except
`/*message.html`, `/*_tabi=`, `/*_pid=`, `/*_fid=` (so no paging through _tabi). Sitemap `/fr/sitemap_offres.aspx`.
Parent `ul.ei_cardgrid.ei_cardgrid_1col`, card (trimmed):
```html
<li class="item"><div class="_c2 ei_card_expanded _c2 _c1 ei_card _c1"><div class="_c1 ei_card_content _c1"><div class="_c1 ei_card_header _c1 _c2  _c2"><span class="_c1 ei_card_title _c1"><a href="/fr/offre.html?annonce=116845">Stage - Assistant(e) gestion taux (F/H)</a><br><span class="_c1 ei_card_subtitle _c1"></span></span></div><div class="_c1 ei_card_body _c1"><ul class="_c1 ei_listdescription _c1"><li>PARIS (75)</li><li>Stage (6 mois)</li><li><small> Date de publication : </small> 05/11/2026</li></ul></div></div><div class="_c1 ei_card_footer _c1">…favoris…</div></div></li>
```
Other real titles on page: "Stage Assistant Fund Manager (F/H)" 116663, "Développeur Quant Front-Office (F/H)" 117761,
"Stage - Janvier 2027 - Analyste Pilotage Stratégique (F/H)" 117711, "CDD - 18 mois - Business support (F/H)" 117746.
ext_id = annonce. Offer page `/fr/offre.html?annonce=N` (enrich generic).

---------------------------------------------------------------------------
## sainoo — Amiral Gestion
`https://amiralgestion.sainoo.com/careers` raw HTML, 6 offers. robots: Allow /.
Parent `div.filtered-jobs`, card:
```html
<a class="job-item clearfix " data-id="10279" href="https://amiralgestion.sainoo.com/jobs/10279?from_careers_page=true&amp;standalone=true"><div class="col-sm-12 title">Stage Juridique / Conformité / Secrétariat Général</div><div class="job-item__info"><div class="col-md-10 col-sm-12 second-row"><div class="info"><div class="location info-item"><i class="fa fa-map-marker fa-fw ca-override__color"></i>Paris</div><div class="employment info-item"><i class="fa fa-clock-o fa-fw ca-override__color"></i>Full-time | Internship</div><div class="salary info-item">&lt; 35K</div><div class="job-function info-item">Administrative</div></div><div class="job-info"><div class="deadline">Deadline: on a rolling basis</div><div class="start-date">Length: 6 months</div></div></div><div class="job-link col-sm-12 col-md-2"><div class="ca-override__color show-job">Apply</div></div></div></a>
```
ids on page: 10279, 9873, 9461, 9050, 1162, 1131. url = `https://amiralgestion.sainoo.com/jobs/{id}` (drop the query).
Known: 1131 "Stage Analyste Financier", 9461 "Analyste Junior – Amiral Climate Solutions (stage)". No publication date shown.

---------------------------------------------------------------------------
## dnca — DNCA Finance
`https://www.dnca-investments.com/carrieres?contract=stage` (filter link of the site; page `/carrieres` lists all).
raw HTML OK (Next.js, offers server-rendered). robots: Allow / (Disallow /admin). Old carrieres.dnca-investments.com/fr = 404.
Card (`ul > li[data-role=offer]`):
```html
<li data-role="offer"><a href="/carrieres/VBPXW547"><span><span>Stagiaire Risques de Marché et Développement</span><span><span>Stage</span><span>Contrôle des Risques</span></span></span><span><span>Paris</span><span>Publiée le<!-- --><!-- -->20/10/2026</span></span><span></span></a></li>
```
Spans: title, contract, service, city, "Publiée le dd/mm/yyyy". ext_id = code after /carrieres/. Page says "2 offres".

---------------------------------------------------------------------------
## comgest — Comgest
`https://www.comgest.com/en/about-us/our-people/careers/internship-offers` and `.../careers/job-offers`.
raw HTML OK. robots: only `/-/media/feature/data/fund-documentation/` disallowed. Each offer is a block:
```html
<div class="rich-text"><p><strong>Job Title:&nbsp;</strong>STAGIAIRE CONFORMITE ET CONTROLE INTERNE </p><p><strong>Job Location:&nbsp;</strong>Paris </p><ul><li> Comgest S.A.<br><br></li></ul><p><strong>Position Type:&nbsp;</strong>Stage (Internship) </p><p><strong>Download the full job description</strong><strong>:&nbsp;</strong><a href="https://www.comgest.com/-/media/files/jobs-and-internships/internships/stagiaire-conformit-et-controle-interne.pdf" class="document-link">STAGIAIRE CONFORMITE ET CONTROLE INTERNE</a></p><p><a href="https://www.comgest.com/en/about-us/our-people/careers/internship-offers/application-form?jobID={E29A4C1F-1D80-41A7-AE87-4E42649BCB64}" class="cta-link">Apply for this position</a></p></div>
```
ext_id = jobID GUID lower-case without braces; url = the PDF (job description) or the page URL. detail_pages = False
(PDF). An earlier offer "Financial Analyst Talent Program" (pdf internship_financial-analyst_talent-program.pdf) is gone.

---------------------------------------------------------------------------
## yello — Deutsche Bank
`https://db.recsolu.com/job_boards/1?locale=en` raw HTML, 25 newest of "74 Results" (complete=False). robots: nothing disallowed.
Parent `div.js-search-results-container` (ul), card:
```html
<li class="search-results__item"><div class="clearfix"><div class="search-results__flag pull-left"></div><div class="search-results__jobinfo pull-left"><a class="search-results__req_title" href="/jobs/wsSne9C62Ef0mymYhfNSyQ?job_board_id=DT5zqeU-qZM-ltrVsIvR9Q">Deutsche Bank Graduate Programme - Investment Bank: Corporate Finance – Paris – 2027</a><div><span>France</span><span>Paris</span></div></div><div class="search-results__post-time pull-right">3d</div></div></li>
```
post-time = relative age ("3d") -> published via parse_relative_age. ext_id = token after /jobs/; url without the query.

---------------------------------------------------------------------------
## carmignac — Carmignac (navigateur)
`https://www.carmignac.com/en-fr/about-us/careers`: plain GET returns a 244-byte JavaScript redirect
("This website requires JS enabled and cookies") = anti-bot. The rendered page has:
```html
<table class="w-full lg:table-fixed"><thead>…Job Title…Contract…Location…</thead><tbody><tr class="group hover:bg-lightgreen-50 border-grey-50 border-b"><td class="py-4 px-6 align-top">Equity Product Specialist</td><td class="py-4 px-6 align-top text-right">Permanent</td><td class="py-4 px-6 align-top text-right">London</td></tr></tbody></table>
```
No link per row (applications by e-mail irecruitment@carmignac.com). ext_id = slug(title + location).
If the headless browser is also refused -> status resiste (do NOT add stealth / anti-detection tricks).

---------------------------------------------------------------------------
## bpifrance — Bpifrance (navigateur)
`https://talents.bpifrance.fr/nos-opportunites/?criteres=stage,finances` and `?criteres=stage,capital-investissement`.
Site was in maintenance during the capture ("Maintenance page", 200, 2 KB): detect that and report status
"erreur" with reason "site en maintenance". Offer URLs look like
`https://talents.bpifrance.fr/opportunites/assistant-gerant-portefeuille-cross-assets-f-h/?id=9986-81`
(ext_id = number before the dash: 9986). Offers are rendered by JavaScript: use self.render(url,
wait_for='a[href*="/opportunites/"]') and collect those links (title = link text or the card heading).
Try a plain GET first: if the links are in the raw HTML, no browser is needed.

---------------------------------------------------------------------------
## roles_watch — Goldman Sachs
robots.txt of higher.gs.com: `Allow: /roles/` then `Disallow: /` -> the search page /campus is forbidden,
only offer pages /roles/{id} can be read. The search API (api-higher.gs.com/gateway/api/v1/graphql) serves the
forbidden page: do not use it. Parser: for each known open offer of the source (source["known_offers"]),
GET its /roles/{id} page: 404/410 or text "no longer available"/"not found" -> res.closed_urls; status "partiel",
reason "robots.txt de Goldman Sachs n'autorise que les fiches d'offres : le robot vérifie les offres connues
mais ne peut pas découvrir les nouvelles", fix "Crée une alerte sur higher.gs.com (Job alerts)". complete=False.
Known: /roles/170877, 170878, 170901, 184029.

## blocked — Pictet
career012.successfactors.eu/robots.txt: `User-agent: * / Disallow: / / Disallow: /*company / Allow: /login`.
Every page of the catalogue is forbidden. Parser checks robots for params.url each run (no page fetched):
still forbidden -> status resiste + reason/fix; allowed -> status "a_configurer", reason "robots.txt l'autorise
maintenant : le lecteur peut être écrit".

## page_watch — Moneta, Eleva
Moneta: `https://www.moneta.fr/contact/stagiaires-apprentis` (no list of offers; spontaneous applications).
Eleva: only JobTeaser (not read). page_watch hashes the main text of params.url; when the hash changes vs
source["page_hash"], emit one offer "La page carrières a changé" (ext_id = "page-" + date) so Luca is notified.
status "sans_catalogue".
