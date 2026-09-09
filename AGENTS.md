# Pravidla pro AI agenty v projektu ha-doma

## Účel a rozsah

Tento repozitář obsahuje konfiguraci Home Assistanta pro skutečnou domácnost.
Upřednostňuj spolehlivost, srozumitelnost a malé ověřitelné změny. Pravidla platí
pro celý repozitář. Konkrétní zadání uživatele určuje rozsah práce; tento soubor
sám o sobě nepovoluje přístup do běžící instalace ani ovládání zařízení.
Jde o pracovní instrukce, nikoli technickou náhradu oprávnění a sandboxu.

## Co můžeš dělat samostatně

- Číst relevantní soubory, hledat souvislosti, vysvětlovat chování a provádět review.
- V rámci zadaného úkolu upravovat lokální konfiguraci a dokumentaci, připravovat
  diff a provádět kontroly bez vedlejších účinků na domácnost.
- Opravovat související chyby nezbytné pro dokončení úkolu. Nesouvisející problémy
  stručně uvést jako nález; nerozšiřovat kvůli nim zadání.
- Běžné vratné pracovní kroky provádět samostatně, pokud nevyžadují domněnky
  o kódu nebo konfiguraci. Při nejasnosti se řídit pravidlem níže.

## Žádné domýšlení kódu

- Nevytvářet domněnky o významu kódu, záměru autora, chování zařízení, entitách,
  hodnotách, jednotkách ani vazbách mezi částmi konfigurace.
- Nejprve hledat odpověď v dostupném kódu, dokumentaci nebo ověřených údajích.
  Pokud odpověď není doložená nebo si zdroje odporují, zeptat se uživatele před
  úpravou, která na ní závisí. Popsat konkrétní nejasnost a vyčkat na vysvětlení.
- Nevybírat potichu „nejpravděpodobnější“ variantu ani neimplementovat odhad.
  Pokračovat lze pouze v nezávislé práci, která dané vysvětlení nepotřebuje.

## Diff při každé změně

- Při každé úpravě předložit uživateli skutečný diff: název souboru, původní
  řádky označené `-` a nové řádky označené `+`, včetně potřebného kontextu.
  Samotný slovní souhrn změn nestačí. Platí to i pro dokumentaci a tato pravidla.
- Diff vztáhnout ke stavu před vlastní úpravou, aby nezahrnoval dřívější změny
  uživatele jako práci agenta. Zahrnout také nové a odstraněné soubory.
- Krátký diff uvést přímo v odpovědi; rozsáhlý zpřístupnit v přehledu změn
  nebo samostatném souboru a připojit odkaz. Tajné hodnoty maskovat a maskování
  výslovně označit.
- Diff předložit po lokální úpravě a vždy před případným commitem či nasazením.
  Pokud se změna následně upraví, předložit i aktualizovaný diff.

## Komentáře v kódu a popis commitu

- Při změně kódu nebo konfigurace doplnit či aktualizovat komentáře u měněné
  logiky: vysvětlit její účel, důvod změny a důležité podmínky nebo vazby.
  Neopisovat každý řádek; komentovat související blok srozumitelně česky.
- Komentáře musí odpovídat výslednému kódu a doloženým informacím. Neznámý
  důvod nebo účel nejprve vyjasnit s uživatelem, nikdy jej do komentáře nevymýšlet.
- Před commitem zkontrolovat, že komentáře odpovídají změně. U čistě textové
  dokumentace vysvětlit změnu v textu a popisu commitu; nevkládat komentáře kódu.
- Každý commit opatřit konkrétním českým předmětem a popisem: co se změnilo,
  proč, jak se liší původní a nové chování a jaké ověření proběhlo nebo chybí.
  Obecné zprávy jako „fix“ nebo „update“ nestačí.
- Požadavek na komentáře sám o sobě není pověřením k provedení commitu.

## Co vyžaduje výslovné pověření uživatele

- Nasazení konfigurace, reload integrací či automatizací, restart Home Assistanta,
  hostitele, Zigbee2MQTT nebo jiného zařízení a aktualizace provozního prostředí.
- Volání služeb/akcí, spouštění skriptů, scén a automatizací v živé instalaci,
  zápisy přes API, MQTT nebo SSH a změny helperů, které mohou spustit automatizace.
  Ani spuštění „jen na zkoušku“ není kontrola bez vedlejších účinků.
- Mazání provozních dat, obnova zálohy, změny přístupů, sítě nebo zabezpečení.
- Commit, push a publikování konfigurace mimo pracovní kopii, pokud to zadání
  nebo již dohodnutý pracovní postup výslovně nezahrnuje.

Pověření již udělené pro konkrétní krok respektuj a nežádej je znovu. Požadavek
„oprav automatizaci“ sám o sobě nepovoluje její nasazení či spuštění. Pokud
pověření chybí, nejprve dokonči lokální přípravu a kontroly; pak předlož konkrétní
změnu, dopad a postup návratu. Na schválení má čekat jen dotčený provozní krok.

## Co nedělat

- Nepřepisovat a nevracet cizí nebo dříve rozpracované změny. Před editací zjistit
  stav Gitu a relevantní diff. Nepoužívat destruktivní Git příkazy bez zadání.
- Nevkládat hesla, tokeny, privátní klíče ani obsah `secrets.yaml` do verzovaných
  souborů, odpovědí, logů nebo externích služeb. Používat `!secret`, kde je podporován.
  Nalezený tajný údaj popsat místem výskytu, nikoli jeho hodnotou.
- Neoslabovat ochranné podmínky, teplotní limity, ochranu baterie ani blokace
  zařízení kvůli pohodlnějšímu řešení. Změna takové ochrany musí být výslovným
  předmětem zadání a mít vysvětlený dopad.
- Nevymýšlet existující entity, zařízení, služby, MQTT témata ani jejich jednotky.
  Nově navržené entity jasně označit a zajistit jejich definici nebo uvést závislost.
- Nevydávat úspěšné načtení YAML za ověření funkčnosti Home Assistanta a netvrdit,
  že změna byla nasazena nebo otestována, pokud k tomu nedošlo.

## Čemu se raději vyhnout

- Plošnému formátování YAML, přesouvání celých bloků a modernizaci syntaxe mimo
  zadání. Zachovat místní styl, komentáře a přehledný diff.
- Přejmenovávání `entity_id`, `unique_id`, ID automatizací a skriptů bez kontroly
  odkazů v konfiguraci, šablonách a dashboardech.
- Přidávání integrací, závislostí nebo nové architektury pro drobnou opravu.
- Slepému nahrazování nedostupných hodnot nulou. U řízení topení, bojleru a FVE
  zvažovat `unknown`, `unavailable`, stáří dat a chování po restartu; bezpečný
  výchozí stav odvodit od konkrétního zařízení, nikoli od univerzálního předpokladu.

## Orientace v konfiguraci

- `configuration.yaml`: hlavní konfigurace, integrace, helpery a šablony.
- `automations.yaml`, `scripts.yaml`, `scenes.yaml`: automatizace, skripty a scény.
- `fve/fve.yaml`: balíček FVE; související řízení je také v hlavních souborech.
- `lovelace.yaml`, `raspi.yaml`: dashboardy. Jejich ovládací prvky mohou spouštět akce.
- `groups.yaml`, `themes.yaml`, `google_calendars.yaml`: další konfigurace;
  skutečné použití ověřit podle odkazů a nastavení instalace.

Repozitář nemusí být úplnou kopií provozní konfigurace. Chybějící include,
tajné údaje, verzi HA a integrace nedoplňovat odhadem.

## Ověření a předání výsledku

1. Přečti dotčenou konfiguraci i navazující automatizace, skripty a šablony.
2. Proveď nejmenší změnu, která splní zadání. U řízení zařízení zkontroluj také
   podmínky, souběhy, opakované spouštění a chování při výpadku dat.
3. Projdi diff, odkazy a syntaxi. Je-li dostupný vhodný YAML validátor, musí
   rozumět značkám HA, například `!include` a `!secret`. Použij dostupnou kontrolu
   konfigurace HA, pokud ji lze provést bez spuštění řízení zařízení; postup
   přizpůsob skutečné verzi a typu instalace. Chybějící prostředí jasně uveď.
4. Před pověřeným nasazením ověř cíl, aktuální provozní verzi souborů, dostupnou
   zálohu a konkrétní návratový postup. Zohledni možné změny provedené přes UI HA.
5. Odpovídej česky a stručně: co se změnilo, proč, co bylo skutečně ověřeno
   a co případně zbývá ověřit nebo nasadit.
