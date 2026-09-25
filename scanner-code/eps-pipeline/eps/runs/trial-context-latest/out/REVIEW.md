# Trial dataset review - `runs/trial-context-v1`

Prompts: `CTX-TRIAGE-v3` / `CTX-RESOLVE-v2`

- Documents: **93**   Rows: **221**
- Departments represented: **35** of 42

## Final status counts

| status | rows |
|---|---|
| `not_needed_triage` | 137 |
| `resolved` | 70 |
| `failed_evidence_not_found` | 6 |
| `not_needed_resolve` | 4 |
| `failed_insertion_format` | 2 |
| `unresolved` | 2 |

Of 70 resolved, **36** carry an opening frame and 34 an inline insertion only.

## Invariants

- Round-trip: **221/221 pass**
- `quote_in_context` populated on every row: **True**
- Rows in == rows out: **221 == 221**
- Exactly one status per row: **True**

## Departments with no rows (7)

- Department for Business, Innovation, Science and Trade
- Department for Culture, Media and Sport
- Department of Transportation
- Department of Veterans Affairs
- Northern Ireland Office
- Office of the Advocate General for Scotland
- UK Export Finance

## All 70 resolved rows

### 1. Attorney General's Office

- **Before:** These free lesson plans, developed with Oak National Academy and the Association of Citizenship Teachers, change that.
- **After:** These free lesson plans, developed with Oak National Academy and the Association of Citizenship Teachers, change that [the lack of high-quality resources to teach rights and laws].
- **Evidence:** too many schools have lacked the high-quality resources to teach that with confidence
- https://www.gov.uk/government/news/attorney-general-launches-free-rule-of-law-lesson-plans-for-every-school-in-england-and-wales

### 2. Cabinet Office

- **Before:** The new digital ID will make that possible, allowing you to log on and prove who you are to access public services more quickly, easily and securely.
- **After:** The new digital ID will make that possible [making public services work for you], allowing you to log on and prove who you are to access public services more quickly, easily and securely.
- **Evidence:** I want to change that and make public services work for you.
- https://www.gov.uk/government/news/government-launches-consultation-on-making-public-services-quicker-easier-and-more-secure-to-access-with-digital-id

### 3. Cabinet Office

- **Before:** So, from now on, top senior civil servants will have their performance marked against KPIs directly set by Ministers. And those under-delivering will be held to account. Instead of the so-called sideways shimmy to another team or another department if you’re not performing, if you fail to perform I’
- **After:** [On senior civil service performance and accountability] So, from now on, top senior civil servants will have their performance marked against KPIs directly set by Ministers. And those under-delivering will be held to account. Instead of the so-called sideways shimmy to another team or another department if you’re not performing, if you fail to perform I’m a
- **Evidence:** I find it hard to believe that only 7 in nearly 7,000 senior civil servants were reported to be on a development plan for underperformance last year. And only 2 of them were dismissed due to poor performance.
- https://www.gov.uk/government/speeches/move-fast-fix-things

### 4. Department for Business and Trade

- **Before:** We’re consulting because we need to get the detail right to ensure these reforms work in practice and guard against unintended consequences from this major change to the labour market.
- **After:** [On ending exploitative zero hours contracts] We’re consulting because we need to get the detail right to ensure these reforms [to end exploitative zero hours contracts] work in practice and guard against unintended consequences from this major change to the labour market.
- **Evidence:** End of exploitative zero hours contracts to give people security and predictability at work | Ministers have today taken the next step to ending exploitative zero hours contracts by launching a consultation to help deliver reforms
- https://www.gov.uk/government/news/end-of-exploitative-zero-hours-contracts-to-give-people-security-and-predictability-at-work

### 5. Department for Business and Trade

- **Before:** That is why, last week, I announced the £11 billion lending package to help small firms grow internationally. It’s a lending commitment from the UK’s five leading banks. Together, they serve half of all British businesses. UK Export Finance will guarantee eligible loans issued by each of them. With 
- **After:** [on supporting start-ups and scale-ups to break into new markets] That is why, last week, I announced the £11 billion lending package to help small firms grow internationally. It’s a lending commitment from the UK’s five leading banks. Together, they serve half of all British businesses. UK Export Finance will guarantee eligible loans issued by each of them.
- **Evidence:** I want to see more start-ups and scale-ups taking risks: building up, branching out and breaking into new markets- backed up by government action.
- https://www.gov.uk/government/speeches/secretary-of-state-keynote-uk-trade-and-export-finance-forum

### 6. Department for Education

- **Before:** That’s why our new schools white paper will sit together with our other work.

Our child poverty strategy, our best start in life strategy, our new approach to children’s social care, our post-16 white paper.
- **After:** [On schools not being left to carry wider social problems alone] That’s why our new schools white paper will sit together with our other work.

Our child poverty strategy, our best start in life strategy, our new approach to children’s social care, our post-16 white paper.
- **Evidence:** But schools can't be alone in this of course. For too long schools have been left to carry the weight of wider social problems alone.
- https://www.gov.uk/government/speeches/secretary-of-states-speech-to-the-national-society-conference

### 7. Department for Education

- **Before:** This new GCSE will help students build a strong understanding of the natural world, alongside the knowledge, skills and hands-on experience to access careers in some of the UK’s fastest growing sectors.
- **After:** This new GCSE [in Natural History] will help students build a strong understanding of the natural world, alongside the knowledge, skills and hands-on experience to access careers in some of the UK’s fastest growing sectors.
- **Evidence:** the new Natural History GCSE is one step closer to being taught in classrooms
- https://www.gov.uk/government/news/new-natural-history-gcse-to-grow-next-generation-of-green-careers

### 8. Department for Education

- **Before:** With extensive fieldwork built in, the GCSE will also get young people out and about exploring local parks, rivers and more – a critical part of childhood as more and more of our worlds are taken up by screens.
- **After:** With extensive fieldwork built in, the GCSE [in Natural History] will also get young people out and about exploring local parks, rivers and more – a critical part of childhood as more and more of our worlds are taken up by screens.
- **Evidence:** the new Natural History GCSE is one step closer to being taught in classrooms
- https://www.gov.uk/government/news/new-natural-history-gcse-to-grow-next-generation-of-green-careers

### 9. Department for Education

- **Before:** So from now on Our Best Start Family Hubs for younger children will cover special educational needs too.

I’m investing more than £200 million in our hubs so that all of them have a dedicated SEND practitioner.
- **After:** [On expanding SEND support in early years] So from now on Our Best Start Family Hubs for younger children will cover special educational needs too.

I’m investing more than £200 million in our hubs so that all of them have a dedicated SEND practitioner.
- **Evidence:** What's crucial is that support starts early. So from now on Our Best Start Family Hubs for younger children will cover special educational needs too.
- https://www.gov.uk/government/speeches/bridget-phillipsons-speech-on-the-schools-white-paper

### 10. Department for Education

- **Before:** So I will bring collaboration to the fore, all schools joining or forming high-quality school trusts.

And that includes schools run by local authorities and local partnerships setting up trusts too.
- **After:** [On school trusts as drivers of collaboration] So I will bring collaboration to the fore, all schools joining or forming high-quality school trusts.

And that includes schools run by local authorities and local partnerships setting up trusts too.
- **Evidence:** And perhaps the most powerful drivers of collaboration are strong school trusts.
- https://www.gov.uk/government/speeches/bridget-phillipsons-speech-on-the-schools-white-paper

### 11. Department for Energy Security and Net Zero

- **Before:** It is a monumental step towards clean power by 2030 and the price secured in this auction is 40% lower than the alternative cost of building and operating a new gas plant.
- **After:** [On the record-breaking Contracts for Difference AR7 offshore wind auction] It is a monumental step towards clean power by 2030 and the price secured in this auction is 40% lower than the alternative cost of building and operating a new gas plant.
- **Evidence:** Now this auction round, known as Contracts for Difference AR7, has secured a record capacity of 8.4GW of offshore wind
- https://www.gov.uk/government/news/record-breaking-auction-for-offshore-wind-secured-to-take-back-control-of-britains-energy

### 12. Department for Energy Security and Net Zero

- **Before:** This investment is the government’s clean energy mission in action- rebuilding our energy security with clean homegrown power and good industrial jobs for South Yorkshire.
- **After:** This investment [£86.5 million in ITM Power's hydrogen manufacturing expansion] is the government’s clean energy mission in action- rebuilding our energy security with clean homegrown power and good industrial jobs for South Yorkshire.
- **Evidence:** Great British Energy, the UK's publicly owned energy company, and government to invest £86.5 million in a UK-first hydrogen project in South Yorkshire
- https://www.gov.uk/government/news/hydrogen-investment-fuels-south-yorkshires-next-industrial-era

### 13. Department for Environment, Food and Rural Affairs

- **Before:** That means couples can pass on up to £5 million pounds without paying inheritance tax on their assets. That’s on top of the existing allowances such as the nil-rate band.
- **After:** [On increasing the inheritance tax threshold to £2.5 million] That means couples can pass on up to £5 million pounds without paying inheritance tax on their assets. That’s on top of the existing allowances such as the nil-rate band.
- **Evidence:** increasing the inheritance tax threshold for Agricultural and Business Property Relief from £1 million to £2.5 million pounds
- https://www.gov.uk/government/speeches/secretary-of-states-address-to-2026-oxford-farming-conference

### 14. Department for Environment, Food and Rural Affairs

- **Before:** we will limit how much land can be put into certain actions and review payment rates for others
- **After:** we will limit how much land can be put into certain actions [within the SFI scheme] and review payment rates for others [other SFI actions]
- **Evidence:** So we're streamlining it. Fewer actions. Less complexity. Easier to apply. | 90% of spending currently goes on fewer than 40 of the 102 actions available.
- https://www.gov.uk/government/speeches/secretary-of-states-address-to-2026-oxford-farming-conference

### 15. Department for Environment, Food and Rural Affairs

- **Before:** Right now, a quarter of the money goes to just 4% of farms.

How can that be fair?

We want to see farmers helping nature thrive everywhere, not just in a few places.

So, we’re considering ways to address this such as an agreement value cap.
- **After:** Right now, a quarter of the money [in SFI funding] goes to just 4% of farms.

How can that be fair?

We want to see farmers helping nature thrive everywhere, not just in a few places.

So, we’re considering ways to address this such as an agreement value cap.
- **Evidence:** we're improving fairness and accessibility. Right now, a quarter of the money goes to just 4% of farms.
- https://www.gov.uk/government/speeches/secretary-of-states-address-to-2026-oxford-farming-conference

### 16. Department for Science, Innovation and Technology

- **Before:** So our ban will include platforms like Snapchat, TikTok, YouTube, Instagram, Facebook and X.
- **After:** [on banning social media for under 16s] So our ban will include platforms like Snapchat, TikTok, YouTube, Instagram, Facebook and X.
- **Evidence:** we will ban social media companies providing their services to under 16s
- https://www.gov.uk/government/speeches/liz-kendalls-statement-on-children-and-social-media

### 17. Department for Science, Innovation and Technology

- **Before:** So we will introduce more highly effective age assurance measures to better support compliance, and I have asked Ofcom to share proposals on these within months.
- **After:** [on children circumventing the social media ban] So we will introduce more highly effective age assurance measures to better support compliance, and I have asked Ofcom to share proposals on these within months.
- **Evidence:** we've seen in Australia that many children will try and succeed in getting around a ban
- https://www.gov.uk/government/speeches/liz-kendalls-statement-on-children-and-social-media

### 18. Department for Science, Innovation and Technology

- **Before:** We’ve cracked down on perpetrators of this vile crime – now we’re turning up the heat on tech firms. Platforms are now required by law to detect and prevent this material.
- **After:** We’ve cracked down on perpetrators of this vile crime [cyberflashing, sending unsolicited nude images] – now we’re turning up the heat on tech firms. Platforms are now required by law to detect and prevent this material.
- **Evidence:** People using dating apps and social media platforms will be better protected from receiving unsolicited nude images, as a new law compelling tech firms to stop this type of content before it reaches users comes into force today
- https://www.gov.uk/government/news/stronger-laws-for-tech-firms-to-ensure-you-dont-see-unsolicited-nudes

### 19. Department for Work and Pensions

- **Before:** Now we’re rolling this out nationwide—because supporting people to stay healthy and employed benefits individuals, businesses, and our economy.
- **After:** Now we’re rolling this out [the WorkWell programme] nationwide—because supporting people to stay healthy and employed benefits individuals, businesses, and our economy.
- **Evidence:** WorkWell, a proven health-and-employment support service, will be rolled out across England
- https://www.gov.uk/government/news/expansion-of-support-scheme-to-help-thousands-of-people-back-into-work

### 20. Department for Work and Pensions

- **Before:** As for a flat-rate scheme that would cost up to £10.3 billion and would simply not be right or fair, given it would be paid to the vast majority who were aware of the changes.
- **After:** [On compensation for 1950s-born women affected by State Pension age communication failures] As for a flat-rate scheme that would cost up to £10.3 billion and would simply not be right or fair, given it would be paid to the vast majority who were aware of the changes.
- **Evidence:** What the Ombudsman investigated was how changes to the State Pension age were communicated, and whether within a specific and narrow time period, there was maladministration and injustice and if so, whether it warrants compensation.
- https://www.gov.uk/government/speeches/government-response-to-parliamentary-and-health-service-ombudsmans-phso-investigation-into-womens-state-pension-age-communications-and-associated

### 21. Department for Work and Pensions

- **Before:** I have heard calls for compensation aimed at lower income pensioners – and we have focused in the past 12 months on raising Pension Credit uptake – but in the context of this decision – a scheme focused on any single income group, still does not specify who may or may not have suffered injustice.
- **After:** I have heard calls for compensation aimed at lower income pensioners – and we have focused in the past 12 months on raising Pension Credit uptake – but in the context of this decision [on State Pension age communication and compensation] – a scheme focused on any single income group, still does not specify who may or may not have suffered injustice.
- **Evidence:** What the Ombudsman investigated was how changes to the State Pension age were communicated, and whether within a specific and narrow time period, there was maladministration and injustice and if so, whether it warrants compensation.
- https://www.gov.uk/government/speeches/government-response-to-parliamentary-and-health-service-ombudsmans-phso-investigation-into-womens-state-pension-age-communications-and-associated

### 22. Department of Agriculture

- **Before:** Today’s action not only reduces government bureaucracy and makes it easier for USDA customers to access our programs, but it also strengthens our ability to take swift action when recipients and cooperators—and even recipients of subawards and subcontracts—are not compliant with Federal law and appl
- **After:** Today’s action [standardizing USDA General Terms and Conditions for all future awards] not only reduces government bureaucracy and makes it easier for USDA customers to access our programs, but it also strengthens our ability to take swift action when recipients and cooperators—and even recipients of subawards and subcontracts—are not compliant with Federal 
- **Evidence:** directing all USDA agencies and staff offices to immediately adopt and implement the first-ever set of USDA General Terms and Conditions for all future awards.
- https://www.usda.gov/about-usda/news/press-releases/2025/12/31/usda-strengthens-national-security-and-protects-taxpayers-standardizing-grant-and-cooperative

### 23. Department of Agriculture

- **Before:** Our mission to Make America Healthy Again continues after the recent release of the Dietary Guidelines for Americans 2025-2030 announcement, with the upcoming purchase of U.S. grown food that will reach those in need, all while benefitting American farmers facing unfair actions from foreign competit
- **After:** Our mission to Make America Healthy Again continues after the recent release of the Dietary Guidelines for Americans 2025-2030 announcement, with the upcoming purchase of U.S. grown food [up to $80 million in specialty crops] that will reach those in need, all while benefitting American farmers facing unfair actions from foreign competitors.
- **Evidence:** USDA's intent to purchase up to $80 million in specialty crops from American farmers and producers to distribute to food banks and nutrition assistance programs across the country.
- https://www.usda.gov/about-usda/news/press-releases/2026/01/13/farm-bureau-convention-secretary-rollins-announces-dairy-margin-coverage-expansion-and-section-32

### 24. Department of Energy

- **Before:** By deploying America’s leading nuclear technology, we are creating thousands of good-paying American jobs, expanding global markets for U.S. nuclear companies, and driving economic growth at home
- **After:** By deploying America’s leading nuclear technology [at the Jaslovské Bohunice Nuclear Power Plant in Slovakia], we are creating thousands of good-paying American jobs, expanding global markets for U.S. nuclear companies, and driving economic growth at home
- **Evidence:** the development of a new, state-owned American 1,200 MWe nuclear unit at the Jaslovské Bohunice Nuclear Power Plant
- https://www.energy.gov/articles/us-energy-secretary-and-slovakias-prime-minister-sign-agreement-advance-us-slovakia-civil

### 25. Department of Health and Social Care

- **Before:** In light of this latest outbreak, I will be asking them to re-examine eligibility for meningitis vaccines.
- **After:** In light of this latest outbreak [of meningococcal disease in Canterbury and east Kent], I will be asking them [the JCVI (Joint Committee on Vaccination and Immunisation] to re-examine eligibility for meningitis vaccines.
- **Evidence:** I'd like to make a statement on the outbreak of meningococcal disease in Canterbury and east Kent. | we obviously follow the expert independent advice of the JCVI
- https://www.gov.uk/government/speeches/secretary-of-state-update-to-the-house-on-meningitis-outbreak

### 26. Department of Health and Social Care

- **Before:** By allowing them to offer vaccinations, we’re using the relationships and expertise that already exist to reach families who need support most.
- **After:** By allowing them [health visitors] to offer vaccinations, we’re using the relationships and expertise that already exist to reach families who need support most.
- **Evidence:** Health visitors are already trusted faces in communities across the country. By allowing them to offer vaccinations
- https://www.gov.uk/government/news/families-to-have-better-access-to-childhood-vaccinations

### 27. Department of Homeland Security

- **Before:** This investment will repair and restore critical public infrastructure across North Carolina, including schools, public safety facilities, utilities, and community services,
- **After:** This investment [of more than $116 million in federal funding] will repair and restore critical public infrastructure across North Carolina, including schools, public safety facilities, utilities, and community services,
- **Evidence:** more than $116 million in federal funding to support the state of North Carolina's recovery from Tropical Storm Helene
- https://www.dhs.gov/news/2026/01/14/secretary-noem-announces-additional-116-million-north-carolina

### 28. Department of Labor

- **Before:** our efforts to reach our goal of 1 million apprentices
- **After:** [on the U.S. Department of Labor] our efforts to reach our goal of 1 million apprentices
- **Evidence:** the U.S. Department of Labor is excited to formally announce its expansive plans for National Apprenticeship Week 2026
- https://www.dol.gov/newsroom/releases/eta/eta20260128-0

### 29. Department of State

- **Before:** And so that’s why we have a quarantine. There’s a quarantine right now in which sanctioned oil shipments – say there’s a boat and that boat is under U.S. sanctions. We go get a court order. We will seize it. That remains in place, and that’s a tremendous amount of leverage that will continue to be i
- **After:** [on Venezuela's oil-based economy and U.S. sanctions leverage] And so that’s why we have a quarantine. There’s a quarantine right now in which sanctioned oil shipments – say there’s a boat and that boat is under U.S. sanctions. We go get a court order. We will seize it. That remains in place, and that’s a tremendous amount of leverage that will continue to b
- **Evidence:** the key to what that regime relies on and – is their economy fueled by oil
- https://www.state.gov/releases/office-of-the-spokesperson/2026/01/secretary-of-state-marco-rubio-with-margaret-brennan-of-cbss-face-the-nation-2

### 30. Department of State

- **Before:** We continue with that quarantine and we expect to see that there will be changes not just in the way the oil industry is run for the benefit of the people, but also so that they stop the drug trafficking, so that we no longer have these gang problems, so that they kick the FARC and the ELN out, and 
- **After:** We continue with that quarantine [seizing sanctioned oil shipments under U.S. court orders] and we expect to see that there will be changes not just in the way the oil industry is run for the benefit of the people, but also so that they stop the drug trafficking, so that we no longer have these gang problems, so that they kick the FARC and the ELN out, and t
- **Evidence:** There's a quarantine right now in which sanctioned oil shipments – say there's a boat and that boat is under U.S. sanctions. We go get a court order. We will seize it.
- https://www.state.gov/releases/office-of-the-spokesperson/2026/01/secretary-of-state-marco-rubio-with-margaret-brennan-of-cbss-face-the-nation-2

### 31. Department of State

- **Before:** So the clear – and we continue to reserve the right to take strikes against drug boats that are bringing drugs towards the United States that are being operated by transnational criminal organizations, including the Cartel de los Soles.
- **After:** [On U.S. enforcement of oil sanctions against Venezuela] So the clear – and we continue to reserve the right to take strikes against drug boats that are bringing drugs towards the United States that are being operated by transnational criminal organizations, including the Cartel de los Soles.
- **Evidence:** We are enforcing American laws with regards to oil sanctions. We have sanctioned entities; we go to court, we get a warrant, we seize those boats with oil.
- https://www.state.gov/releases/office-of-the-spokesperson/2026/01/secretary-of-state-marco-rubio-with-kristen-welker-of-nbcs-meet-the-press

### 32. Department of the Interior

- **Before:** This program invests directly in Native youth, builds a skilled workforce for the future and supports the Trump administration’s priority to strengthen public safety and create practical career opportunities through education and training.
- **After:** This program [the Native Youth Firefighter Training Program] invests directly in Native youth, builds a skilled workforce for the future and supports the Trump administration’s priority to strengthen public safety and create practical career opportunities through education and training.
- **Evidence:** Through the Native Youth Firefighter Training Program, high school and post-secondary students receive hands-on instruction, mentorship and technical training
- https://www.doi.gov/pressreleases/department-interior-expands-training-pathway-native-youth-wildland-fire-careers

### 33. Foreign, Commonwealth and Development Office

- **Before:** I announced a further $27 million dollars to support survivors of sexual violence.
- **After:** [on Sudan aid, speaking in Chad] I announced a further $27 million dollars to support survivors of sexual violence.
- **Evidence:** And in Chad, I announced a further $27 million dollars to support survivors of sexual violence.
- https://www.gov.uk/government/speeches/let-this-be-the-time-that-the-world-comes-together-to-end-the-cycle-of-bloodshed-in-sudan-uk-statement-at-the-un-security-council

### 34. Foreign, Commonwealth and Development Office

- **Before:** And this week we joined the US and France in proposing they be designated by the UN Security Council too. We are confronting impunity by supporting the ICC’s Sudan investigation so we can bring perpetrators to justice.
- **After:** And this week we joined the US and France in proposing they be designated [several senior RSF commanders linked to atrocities in El Fasher] by the UN Security Council too. We are confronting impunity by supporting the ICC’s Sudan investigation so we can bring perpetrators to justice.
- **Evidence:** The UK has already sanctioned several senior RSF commanders linked to the atrocities committed in El Fasher. And this week we joined the US and France in proposing they be designated by the UN Security Council too.
- https://www.gov.uk/government/speeches/let-this-be-the-time-that-the-world-comes-together-to-end-the-cycle-of-bloodshed-in-sudan-uk-statement-at-the-un-security-council

### 35. Foreign, Commonwealth and Development Office

- **Before:** arms restrictions need to be enforced and extended
- **After:** arms restrictions [on arms flows into Darfur] need to be enforced and extended
- **Evidence:** The Fact-Finding Mission has said that it will report back further on investigations into breaches of the UN arms embargo into Darfur, but arms restrictions need to be enforced and extended
- https://www.gov.uk/government/speeches/let-this-be-the-time-that-the-world-comes-together-to-end-the-cycle-of-bloodshed-in-sudan-uk-statement-at-the-un-security-council

### 36. General Services Administration

- **Before:** This interim contract helps execute President Trump’s vision of a more efficient federal government, and ensure there are no disruption in services from contractors already proven to deliver necessary services,
- **After:** This interim contract [the GLS Interim leasing support services contract] helps execute President Trump’s vision of a more efficient federal government, and ensure there are no disruption in services from contractors already proven to deliver necessary services,
- **Evidence:** GSA Leasing Support Services (GLS) Interim contract will be a bridge for GSA's leasing support services
- https://www.gsa.gov/about-gsa/newsroom/news-releases/gsa-awards-interim-leasing-support-services-contract-01132026

### 37. General Services Administration

- **Before:** This extension will enable GSA to take a deeper dive into the services provided to ensure we are optimizing contracts moving forward.
- **After:** This extension [of current GLS Plus contracts via the GLS Interim contract] will enable GSA to take a deeper dive into the services provided to ensure we are optimizing contracts moving forward.
- **Evidence:** awarded nine GLS Interim contracts to current GLS Plus contract holders for up to 12 months. This proactive step extends the current contracts
- https://www.gsa.gov/about-gsa/newsroom/news-releases/gsa-awards-interim-leasing-support-services-contract-01132026

### 38. HM Treasury

- **Before:** Thanks to our tax cuts, families will be able to enjoy more of the little treats and days out that make the British summer holidays so special.
- **After:** Thanks to our tax cuts [cutting VAT from 20% to 5% on eligible activities], families will be able to enjoy more of the little treats and days out that make the British summer holidays so special.
- **Evidence:** the Chancellor cut VAT from 20% to 5% on eligible activities including family tickets to the cinema, admission tickets for both children and adults to amusement parks, and children's meals in restaurants
- https://www.gov.uk/government/news/great-british-summer-savings-families-can-now-find-deals-closer-to-home-at-the-click-of-a-button

### 39. HM Treasury

- **Before:** …and at the same time, I made bold changes to the fiscal rules that meant I was able to invest an additional £120bn in my Spending Review to restore our public services, and build the housing, energy and transport infrastructure that is so critical for economic growth.
- **After:** [On her first Budget] …and at the same time, I made bold changes to the fiscal rules that meant I was able to invest an additional £120bn in my Spending Review to restore our public services, and build the housing, energy and transport infrastructure that is so critical for economic growth.
- **Evidence:** In my first Budget, I repaired the public finances, whilst setting out a path of fiscal consolidation to bring borrowing costs down…
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 40. HM Treasury

- **Before:** …cutting inflation by reducing energy bills, freezing prescription charges and freezing rail fares…
- **After:** [On her second Budget] …cutting inflation by reducing energy bills, freezing prescription charges and freezing rail fares…
- **Evidence:** At my second Budget last year, I built on these strong foundations to bear down on the cost of living…
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 41. HM Treasury

- **Before:** …and I have increased investment in city region transport, supported Development Corporations in our two growth corridors, and allocated money to new place-based funds to boost defence, innovation and creative clusters in our regions and our nations.
- **After:** [On boosting regional investment] …and I have increased investment in city region transport, supported Development Corporations in our two growth corridors, and allocated money to new place-based funds to boost defence, innovation and creative clusters in our regions and our nations.
- **Evidence:** To boost regional investment, I have reformed the Treasury's Green Book – our investment manual – so every part of our country is given a fair hearing…
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 42. HM Treasury

- **Before:** That is why we stepped in to save British steel and prevent Britain’s steel capacity from being fundamentally undermined…

…so that our infrastructure, our industries and our security are not dependent on foreign imports.
- **After:** [On the principle that economic security is national security] That is why we stepped in to save British steel and prevent Britain’s steel capacity from being fundamentally undermined…

…so that our infrastructure, our industries and our security are not dependent on foreign imports.
- **Evidence:** instead recognising that economic security is national security.
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 43. HM Treasury

- **Before:** …and that is why I have changed our procurement rules, so that government procurement is no longer a cheque for global incumbents but a launchpad for British businesses…

…ensuring we can buy British when it is critical to our national security – for steel, for shipbuilding…

…and now for AI.
- **After:** [On backing British businesses through industrial strategy] …and that is why I have changed our procurement rules, so that government procurement is no longer a cheque for global incumbents but a launchpad for British businesses…

…ensuring we can buy British when it is critical to our national security – for steel, for shipbuilding…

…and now for AI.
- **Evidence:** That is a fundamental principle of securonomics and of our industrial strategy
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 44. HM Treasury

- **Before:** our largest pension funds invested an additional £10bn into private markets because of the changes that I have made
- **After:** our largest pension funds invested an additional £10bn into private markets because of the changes that I have made [to pension fund investment rules]
- **Evidence:** I am turning Britain's savers into investors through changes to ISAs and to financial advice, Last year, our largest pension funds invested an additional £10bn into private markets because of the changes that I have made
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 45. HM Treasury

- **Before:** …launching a new UK Export Finance guarantee scheme, to help small businesses to start exporting…

…and expanding the highly successful Growth Guarantee Scheme from the British Business Bank…

…more than doubling SME lending that it will support to £3.5bn per year…

…and increasing the number of bus
- **After:** [On boosting SME lending] …launching a new UK Export Finance guarantee scheme, to help small businesses to start exporting…

…and expanding the highly successful Growth Guarantee Scheme from the British Business Bank…

…more than doubling SME lending that it will support to £3.5bn per year…

…and increasing the number of businesses supported from 8,000 to 20
- **Evidence:** And I have boosted SME lending including through the changes I announced yesterday in Gateshead to help businesses grow, invest and create jobs…
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 46. HM Treasury

- **Before:** …so that we can finalise ambitious agreements on agrifoods, emissions trading, electricity and a Youth Experience Scheme.
- **After:** [On the next UK-EU summit] …so that we can finalise ambitious agreements on agrifoods, emissions trading, electricity and a Youth Experience Scheme.
- **Evidence:** I want to see the next UK-EU summit rescheduled as soon as possible…
- https://www.gov.uk/government/speeches/rachel-reeves-mansion-house-2026-speech

### 47. Home Office

- **Before:** Under these reforms, forces will no longer be policing perfectly legal tweets. Instead, they will be doing what they do best: patrolling our streets, catching criminals and keeping communities safe.
- **After:** Under these reforms [replacing non-crime hate incidents (NCHIs) with a new system], forces will no longer be policing perfectly legal tweets. Instead, they will be doing what they do best: patrolling our streets, catching criminals and keeping communities safe.
- **Evidence:** NCHIs will be replaced with a system that lets police get on with their jobs – preventing and fighting real criminals to make communities safer.
- https://www.gov.uk/government/news/government-response-to-non-crime-hate-incidents-final-report

### 48. Home Office

- **Before:** So we are attracting high-skilled workers…

While, at the same time, introducing new controls to migration routes…

Which has now seen net migration fall by nearly 70%.
- **After:** [On legal migration reforms] So we are attracting high-skilled workers…

While, at the same time, introducing new controls to migration routes…

Which has now seen net migration fall by nearly 70%.
- **Evidence:** On legal migration, that means ensuring we are attracting those who can and will contribute to this country…
- https://www.gov.uk/government/speeches/home-secretarys-speech-on-immigration-5-march-2026

### 49. Home Office

- **Before:** Secondly, there will be certain conditions that must be met in order to qualify:

A clean criminal record…

No debt to the taxpayer…

A history of being in work and paying taxes…

And higher standards of English language.
- **After:** [On conditions for settlement in the UK] Secondly, there will be certain conditions that must be met in order to qualify:

A clean criminal record…

No debt to the taxpayer…

A history of being in work and paying taxes…

And higher standards of English language.
- **Evidence:** there will be certain conditions that must be met in order to qualify
- https://www.gov.uk/government/speeches/home-secretarys-speech-on-immigration-5-march-2026

### 50. Home Office

- **Before:** That means applying any rule changes to those who are in the UK today…

But have not yet received settled status.

If we do not, we will see a £10 billion pound drain on our public finances…

And further strain on public services – like housing and healthcare - already under immense pressure.
- **After:** [On addressing the settlement of hundreds of thousands of low-skilled workers] That means applying any rule changes to those who are in the UK today…

But have not yet received settled status.

If we do not, we will see a £10 billion pound drain on our public finances…

And further strain on public services – like housing and healthcare - already under immen
- **Evidence:** address the challenge posed by the impending settlement of the hundreds of thousands of low-skilled workers and their dependants…
- https://www.gov.uk/government/speeches/home-secretarys-speech-on-immigration-5-march-2026

### 51. Home Office

- **Before:** This will see a reduction in initial leave to remain for refugees, from five years to two and a half years.

At that point, a refugee’s need for protection will be reviewed.

If they still require it, their status will be renewed.

If they do not, and their home country is safe, they will return hom
- **After:** [On a change to migration rules coming into effect this month] This will see a reduction in initial leave to remain for refugees, from five years to two and a half years.

At that point, a refugee’s need for protection will be reviewed.

If they still require it, their status will be renewed.

If they do not, and their home country is safe, they will return 
- **Evidence:** That starts with a change to migration rules, which comes into effect this month.
- https://www.gov.uk/government/speeches/home-secretarys-speech-on-immigration-5-march-2026

### 52. Home Office

- **Before:** Today, I can announce that I am suspending certain visa routes for a further 4 countries…

Afghanistan, Cameroon, Myanmar and Sudan…

Where abuse has been unacceptably high.
- **After:** Today, I can announce that I am suspending certain visa routes [where abuse has been unacceptably high] for a further 4 countries…

Afghanistan, Cameroon, Myanmar and Sudan…

Where abuse has been unacceptably high.
- **Evidence:** Where abuse has been unacceptably high.
- https://www.gov.uk/government/speeches/home-secretarys-speech-on-immigration-5-march-2026

### 53. Home Office

- **Before:** Jonathan Hall therefore recommended the creation of a new offence. This legislation will also be brought forward as soon as parliamentary time allows.
- **After:** Jonathan Hall therefore recommended the creation of a new offence [for planning an attack without an underlying ideology]. This legislation will also be brought forward as soon as parliamentary time allows.
- **Evidence:** if you are planning an attack without an underlying ideology, there is no crime on the statute book. Jonathan Hall therefore recommended the creation of a new offence.
- https://www.gov.uk/government/speeches/the-southport-inquiry-phase-1-report

### 54. Ministry of Defence

- **Before:** And that’s why, this year, we are deploying our carrier group where it is most needed – the High North – and why we’re leading NATO’s new mission, Arctic Sentry.
- **After:** [on the UK's resolve to confront Russian aggression] And that’s why, this year, we are deploying our carrier group where it is most needed – the High North – and why we’re leading NATO’s new mission, Arctic Sentry.
- **Evidence:** Our resolve to track, expose and confront the Russian threat remains absolute.
- https://www.gov.uk/government/speeches/defence-secretary-no9-speech-09-april-2026

### 55. Ministry of Defence

- **Before:** The UK, at the request from the US, supported this operation as part of global efforts to crack down on sanctions-busting and shadow shipping activity.
- **After:** The UK, at the request from the US, supported this operation [to intercept the Motor Vessel BELLA 1 in the North Atlantic] as part of global efforts to crack down on sanctions-busting and shadow shipping activity.
- **Evidence:** the US conducted a military operation to intercept the Motor Vessel BELLA 1 in the North Atlantic during its voyage to Russia
- https://www.gov.uk/government/speeches/defence-secretary-statement-on-us-interception-of-bella-1-and-coalition-of-the-willing-meeting

### 56. Ministry of Housing, Communities and Local Government

- **Before:** …and to support the delivery of more homes, we will make available £2.5 billion of low-interest loans to Private Registered Providers.
- **After:** [On rebuilding sector capacity for social housing] …and to support the delivery of more homes, we will make available £2.5 billion of low-interest loans to Private Registered Providers.
- **Evidence:** A combination of building safety requirements, rising costs, and real-terms rent cuts has weakened the capacity of housing associations and councils. This Government is committed to strengthening it. Alongside grant funding, the Government 
- https://www.gov.uk/government/speeches/housing-secretary-speech-to-lloyds-social-housing-forum

### 57. Ministry of Housing, Communities and Local Government

- **Before:** I want to see housing association tenants benefit from this too, so we are opening a consultation to listen to ideas on how best to make that happen.
- **After:** I want to see housing association tenants benefit from this too [the Right to Manage and greater tenant control over homes], so we are opening a consultation to listen to ideas on how best to make that happen.
- **Evidence:** Our new Right to Manage will give residents more opportunity to take over how their homes are managed if their social landlord fails to improve substandard services. That's in addition to our Social Housing Innovation Fund, which has funded
- https://www.gov.uk/government/speeches/housing-secretary-speech-to-lloyds-social-housing-forum

### 58. Ministry of Justice

- **Before:** That’s why the UK wholeheartedly endorses the Call to Action to all development actors to accelerate support for locally led development, and we encourage you to join us.
- **After:** [on supporting country-led development] That’s why the UK wholeheartedly endorses the Call to Action to all development actors to accelerate support for locally led development, and we encourage you to join us.
- **Evidence:** First, we must work alongside partners as they set their own agendas, aligning our support and finance behind their aspirations for their own development.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 59. Ministry of Justice

- **Before:** This means tackling illicit finance and corruption. Which I see as one of the great progressive causes of our times.
- **After:** [on building self-sufficiency and economic resilience] This means tackling illicit finance and corruption. Which I see as one of the great progressive causes of our times.
- **Evidence:** And finally, to deliver this, we must support partners in building self-sufficiency and fiscal resilience.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 60. Ministry of Justice

- **Before:** It also means mobilising more private capital and the City of London is a hub of green finance and we want it to become a hub of global development finance too.
- **After:** [on building self-sufficiency and economic resilience] It also means mobilising more private capital and the City of London is a hub of green finance and we want it to become a hub of global development finance too.
- **Evidence:** And finally, to deliver this, we must support partners in building self-sufficiency and fiscal resilience.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 61. Ministry of Justice

- **Before:** So we are working with senior leaders from across the investment community to address practical barriers to scaling investment in developing countries.
- **After:** [on mobilising private capital for developing countries] So we are working with senior leaders from across the investment community to address practical barriers to scaling investment in developing countries.
- **Evidence:** It also means mobilising more private capital and the City of London is a hub of green finance and we want it to become a hub of global development finance too.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 62. Ministry of Justice

- **Before:** Whether that’s ensuring greater voice across the debt architecture through the new Borrowers’ Platform, co-chairing the current World Bank Shareholding Review, reforming the UN Security Council to include permanent representation from the African continent, India, Germany, Brazil and Japan or ensuri
- **After:** [on how the UK champions greater Global South representation] Whether that’s ensuring greater voice across the debt architecture through the new Borrowers’ Platform, co-chairing the current World Bank Shareholding Review, reforming the UN Security Council to include permanent representation from the African continent, India, Germany, Brazil and Japan or ensu
- **Evidence:** Yvette Cooper set out earlier today how the UK is working in partnership to champion this shift across the system.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 63. Ministry of Justice

- **Before:** That is why we have always supported the vision of Least Development Countries to get more finance and decision-making power flowing to locally led climate action and to communities on the front line.
- **After:** [on prioritising climate and development together] That is why we have always supported the vision of Least Development Countries to get more finance and decision-making power flowing to locally led climate action and to communities on the front line.
- **Evidence:** Third, we must prioritise and protect the parts of the system that protect us. There is no development without climate action and no climate action without development.
- https://www.gov.uk/government/speeches/deputy-prime-minister-global-partnerships-conference-speech-shifting-the-power-modern-partnerships-in-practice

### 64. National Aeronautics and Space Administration

- **Before:** By expanding access and sharpening competition in low Earth orbit, these missions are building the capabilities NASA will rely on as we move outward to the Moon, Mars, and beyond.
- **After:** By expanding access and sharpening competition in low Earth orbit, these missions [private astronaut missions to the International Space Station] are building the capabilities NASA will rely on as we move outward to the Moon, Mars, and beyond.
- **Evidence:** NASA and Axiom Space have signed an order for the fifth private astronaut mission to the International Space Station
- https://www.nasa.gov/news-release/nasa-selects-axiom-space-for-fifth-private-mission-to-space-station

### 65. National Aeronautics and Space Administration

- **Before:** recalibrating our acquisition strategy — including a build versus buy versus service procurement approach — restoring core competencies through initiatives like converting contractors to civil servant roles and increasing our launch cadence
- **After:** [On NASA's response to the ASAP 2025 annual report] recalibrating our acquisition strategy — including a build versus buy versus service procurement approach — restoring core competencies through initiatives like converting contractors to civil servant roles and increasing our launch cadence
- **Evidence:** We were already on the path to implementing change and this report only adds more urgency, added Isaacman.
- https://www.nasa.gov/news-release/nasas-aerospace-safety-advisory-panel-releases-2025-annual-report

### 66. National Science Foundation

- **Before:** This investment will equip thousands of educators with the tools needed to bring AI and computer science into the classroom, turning the Executive Order into action and preparing the next generation to become innovators, builders and leaders.
- **After:** This investment [the $11 million NSF award to CSTA] will equip thousands of educators with the tools needed to bring AI and computer science into the classroom, turning the Executive Order [on Advancing Artificial Intelligence Education for American Youth] into action and preparing the next generation to become innovators, builders and leaders.
- **Evidence:** The U.S. National Science Foundation today announced an $11 million award to the Computer Science Teachers Association (CSTA) | the executive order on Advancing Artificial Intelligence Education for American Youth
- https://www.nsf.gov/news/nsf-invests-11m-expand-ai-professional-development-k-12

### 67. Office of Personnel Management

- **Before:** This rule preserves merit-based hiring, veterans’ preference, and whistleblower protections while ensuring senior career officials responsible for advancing President Trump’s agenda can be held to the same performance expectations that exist throughout much of the American workforce.
- **After:** This rule [establishing Schedule Policy/Career in the excepted service] preserves merit-based hiring, veterans’ preference, and whistleblower protections while ensuring senior career officials responsible for advancing President Trump’s agenda can be held to the same performance expectations that exist throughout much of the American workforce.
- **Evidence:** the final rule establishing Schedule Policy/Career in the excepted service
- https://www.opm.gov/news/news-releases/opm-finalizes-schedule-policycareer-rule-to-strengthen-accountability

### 68. Scotland Office

- **Before:** This is another tremendous result delivered by the UK Government for Scotland’s world-renowned whisky industry. From Delhi to Beijing, this government is opening doors for Scottish exporters and putting money in the pockets of working people across Scotland.
- **After:** This is another tremendous result [a Scotch whisky tariff cut in China from 10% to 5%] delivered by the UK Government for Scotland’s world-renowned whisky industry. From Delhi to Beijing, this government is opening doors for Scottish exporters and putting money in the pockets of working people across Scotland.
- **Evidence:** China agreeing to cut tariffs on Scotch whisky from 10 per cent to 5 per cent
- https://www.gov.uk/government/news/prime-minister-secures-scotch-whisky-tariff-cut-in-china-worth-250-million

### 69. Scotland Office

- **Before:** This new investment will allow local leaders to decide how best to use the funding, which could include projects to improve infrastructure, business support or skills development. The UK Government will now work with local partners to develop investment plans tailored to each region.
- **After:** This new investment [of £140 million from the Local Growth Fund] will allow local leaders to decide how best to use the funding, which could include projects to improve infrastructure, business support or skills development. The UK Government will now work with local partners to develop investment plans tailored to each region.
- **Evidence:** The UK Government is today backing regional economies across Scotland with £140 million of new investment.
- https://www.gov.uk/government/news/140m-scottish-local-growth-fund-to-drive-economic-growth

### 70. Small Business Administration

- **Before:** the SBA is extending deadlines to give innocent residents more time to secure their permits and access the loans they need to begin construction
- **After:** [on the one-year anniversary of the Los Angeles County wildfires] the SBA is extending deadlines to give innocent residents more time to secure their permits and access the loans they need to begin construction
- **Evidence:** Today, on the one-year anniversary of the Los Angeles County wildfires, the U.S. Small Business Administration (SBA) announced it is once again extending disaster relief deadlines
- https://legacy.sba.gov/article/2026/01/07/one-year-anniversary-california-wildfires-sba-extends-disaster-relief-deadlines-local-bureaucrats


## Unresolved and failed

- `failed_insertion_format` - That’s why, as Chief Secretary to the Treasury, I launched “project reset”. A programme to slash the bureaucracy and enable civil servants to move fas
  - evidence offered: One decision could take on average up to nine months with little to show for it at the end.
- `unresolved` - GBR will have a legal duty to promote rail freight in line with our 2050 freight target.
  - note: The document mentions 'our 2050 freight target' but provides no further detail about what that target is. The referent cannot be identified with confidence from the document alone.
- `failed_evidence_not_found` - Today’s awards show that this Administration is committed to restoring a secure domestic nuclear fuel supply chain capable of producing the nuclear fu
  - evidence offered: the Department announced task order awards with three companies... The following companies were awarded task orders totaling $2.7 billion to provide enrichment services for LEU and HALEU
- `failed_evidence_not_found` - They need investment from private companies who are only going to invest under certain guarantees and conditions. That has to go to the benefit of the
  - evidence offered: Their oil industry is completely destroyed. It's destroyed. All those oilfields that used to produce a lot — and wealth for their country and their people, those things are decrepit. They're bankrupt.
- `failed_evidence_not_found` - Until they address it, they will continue to face this oil quarantine, they will continue to face pressure from the United States. We will continue to
  - note: 'They' and 'Until they address it' refer to Venezuela's new leadership; 'the things we need to see addressed' refers to the list of U.S. demands Rubio outlines.
  - evidence offered: There are other people in charge of the military and police apparatus there. They're going to have to decide now what direction they want to go | we go to court, we get a warrant, we seize those boats
- `failed_evidence_not_found` - Today, we are taking an important step to undo a Biden Administration rule that treated our state partners unfairly. If the SIPs are approved as propo
  - evidence offered: the Biden-Harris administration took it a step further by improperly finalizing the "Good Neighbor Plan" | the agency is proposing to approve eight states' State Implementation Plans (SIPs) pertaining
- `failed_evidence_not_found` - Taxpayer-funded accommodation will be reserved for those who:

Have no right to work…

And will otherwise be destitute.
  - evidence offered: The generosity of the British people will become conditional… On those seeking asylum following the law… And not working illegally.
- `failed_evidence_not_found` - This government will now pilot a similar model for families who are failed asylum seekers.

A small number of whom will now be offered an increased in
  - evidence offered: One of the great successes of the Danish model has been the use of incentives… which sees 95% of removals take place voluntarily.
- `failed_insertion_format` - Using military, economic and diplomatic instruments to ensure the conclusion of a peace agreement, supporting the development of Ukraine’s defence cap
  - evidence offered: Yesterday's Declaration advances our work significantly. It confirms the UK and France will a "take a leading role" in:
- `unresolved` - We have also introduced equal access to government remediation funding schemes, providing over £1 billion of new investment between 2026-27 and 2029-3
  - note: The document does not name or describe the specific government remediation funding schemes being referenced; it only mentions them in passing without identifying them.
