# Ceny paliv v Home Assistantu

## Stav přípravy

Google Apps Script byl po výslovném schválení nasazen 10. 9. 2026 v 8:51 jako
**verze 5** do stejné aktivní implementace. URL, vlastnost `HA_TOKEN` a přístupová
oprávnění se nezměnily. Uložený kód byl zpětně přečten a odpovídá schválené
úpravě. Veřejný HTTP požadavek bez tokenu skutečně vrátil
`{"ok":false,"error":"unauthorized"}`.

Konfigurace HA je připravená ve větvi `codex/ceny-paliv`, ale do běžícího HA
zatím nebyla nahrána. Zdrojový skript a tři listy tabulky byly přečteny
10. 9. 2026. Čas kontroly nabídek v tabulce je 9. 9. 2026.

## Zapojení

[Zdrojový Google Sheet](https://docs.google.com/spreadsheets/d/19xq-1TWFLIzEax05AWibkNSTMfRBEw8Oqv1ujXdRAnk/edit)
obsahuje listy `HA data`, `RUF HA data` a `Válcové HA data`.
Od třetího řádku mají sedm sloupců: klíč, prodejce, cena Kč/kg, změna
za deset dní Kč/kg, skladový stav, čas kontroly a URL nabídky.
Číselné buňky jsou skutečná čísla; jednotky patří do jejich formátování.

- `tools/fuel_prices_api.gs`: kopie stávajícího exportéru rozšířená o
  `valcove` a zahrnutí těchto nabídek do společného slovníku `items`.
  Původní `pellets`, `ruf`, `price_per_kg` a `change_10d_per_kg` se zachovávají.
  Skript pouze čte tabulku. Ověření pomocí vlastnosti `HA_TOKEN` se nemění.
- `ceny_paliv_rest.yaml`: jeden požadavek každých šest hodin, timeout 30 sekund.
  Vytváří původní souhrnný `sensor.ceny_paliv_api` a 16 cenových senzorů.
  `configuration.yaml` tento soubor načítá přes `!include`.
- `ceny_paliv_dashboard.yaml`: tři záložky s Bubble Card.
  Je registrovaný v `lovelace.dashboards.ceny-paliv`; existující hlavní
  dashboard zůstává ve storage režimu.

Cena senzoru je v Kč/kg a zachovává přesnost zdroje. Atributy obsahují
`seller`, `change_10d_per_kg`, `status`, `checked_at` a `source`.
Desetidenní změnu počítá zdrojový projekt. HA ji znovu nepřepočítává.
Prázdná změna zůstává `null`; dashboard ji zobrazuje jako pomlčku.
Skutečná nulová změna se zobrazuje jako nula.

Chyba API, ne-JSON odpověď, chybějící položka nebo nečíselná cena znamená
`unavailable`, nikoli cenu nula. Skladová nedostupnost sama neodstraňuje cenu:
stav zboží je nadále viditelný vedle ní. Čas `generated_at` je čas stažení;
`checked_at` je čas ověření nabídky ve zdrojovém projektu. Zobrazený čas kontroly
je převeden do Europe/Prague. Data se podle stáří automaticky nevyřazují;
konkrétní hranice jejich platnosti zatím nebyla dohodnuta.

## Nové entity

Očekávaná ID jsou `sensor.ceny_paliv_<klíč>`. Název REST senzoru a unique_id
jsou tomu přizpůsobené. Skutečně přidělená ID je třeba ověřit v registru HA:
při kolizi může Home Assistant přidat číselný suffix.

| Kategorie | Klíče nabídek |
| --- | --- |
| Pelety (10) | `evans`, `a1_royal`, `kohutovy_mm_royal`, `cdp_pfeifer`, `a1_rettenmeier`, `waldera`, `biomac_top_a1`, `premium_pellets_jenikov`, `lysuvky_royal`, `topiva_strom_mt` |
| RUF (3) | `evans_ruf_mosaic`, `mosaic_ruf_direct`, `topiva_strom_ruf` |
| Válcové (3) | `evans_tmave_hard`, `a1_tmave_hard`, `biomac_energo_hard` |

## Nasazení po výslovném pověření

1. V [Apps Script projektu](https://script.google.com/home/projects/1-4UYvq7PRTqKhCA7YehEn7sf_M-zFTaiICm979t7s7UHfxX6NW8BvfdW/edit)
   znovu porovnat aktuální kód s přečtenou verzí a uchovat zálohu.
   Soubor `Kód.gs` nahradit ověřeným obsahem `tools/fuel_prices_api.gs`.
   Vlastnost `HA_TOKEN` a oprávnění ponechat beze změny.
2. Ve správě implementací upravit současnou aktivní implementaci,
   vytvořit novou verzi a zachovat její URL. Při kontrole byla aktivní
   **verze 4 z 4. 8. 2026 18:46**, spuštění jako vlastník a přístup Kdokoli;
   přístup k datům uvnitř skriptu omezuje token.
3. Ověřit, že požadavek bez správného tokenu vrací `unauthorized`, a se
   správným tokenem vrací `ok: true`, všech 16 položek a tři kategorie.
   Tajný token ani úplnou autentizovanou URL nevypisovat do logu.
4. Před kopírováním do HA zjistit cílovou instalaci, její verzi a aktuální
   provozní konfiguraci včetně změn přes UI. Vytvořit zálohu dotčených souborů
   a použít jen změny tohoto diffu.
5. V provozním `secrets.yaml` musí být `fuel_prices_api_url`:
   URL aktivní webové aplikace končící `/exec` doplněná o
   `?token=<hodnota HA_TOKEN>`. Zástupný text je nutné nahradit skutečnou
   hodnotou přímo v tajném souboru; ta nepatří do Git repozitáře.
   Soubor `secrets.yaml` v této pracovní kopii není a nebyl vytvářen.
6. Zkopírovat `ceny_paliv_rest.yaml`, `ceny_paliv_dashboard.yaml` a odpovídající
   úpravu `configuration.yaml`. Ověřit, že je ve frontendu nainstalovaná
   a registrovaná Bubble Card. Její soubory ani umístění v živém HA
   nejsou v repozitáři doložené, proto se cesta k modulu nepřidává odhadem.
7. Provést kontrolu konfigurace přesné verze HA. Restart provést až s
   výslovným pověřením, poté ověřit 17 entit a dashboard `ceny-paliv`.
   Pokud původní souhrnný senzor ještě neexistuje, vznikne spolu s cenovými.
   Dashboard slouží k prohlížení a klepnutí otevírá detail entity.

## Návrat

Apps Script: ve správě stejné implementace znovu vybrat verzi 4.
Zachová se URL i token; válcové brikety přestanou být exportované.
Lokální soubor `.fuel-prices-original.gs` je neversionovaná kopie původního
kódu bez tajného tokenu pro případnou obnovu editoru.

HA: ze zálohy obnovit předchozí provozní `configuration.yaml` a případné
předchozí soubory cenového přehledu, ověřit konfiguraci a provést pověřený
restart. Nové soubory přestanou být načítané. Případné záznamy nových entit
v registru se tím automaticky nemažou.

## Ověření a omezení

`python tools/check.py` v prostředí podle `TESTOVANI.md` kontroluje všechny
YAML soubory a 21 lokálních testů. Cílené testy vykonávají skutečné Jinja šablony
a skutečný JavaScript exportéru s náhradami služeb Google. Ověřují všechny
klíče, export tří skupin, ochranu tokenem, chybná data, nulovou i chybějící
desetidenní změnu a formátování zobrazení.

Chybí místní include adresáře `themes`. Nebyl proveden `check_config` konkrétní
verze HA, kontrola živých entit ani vizuální ověření Bubble Card v HA.
Přímé načtení webového API v dostupném prohlížeči skončilo
`ERR_BLOCKED_BY_CLIENT`; následný HTTP požadavek mimo prohlížeč ověřil správné
odmítnutí přístupu bez tokenu. Autentizovaná HTTP odpověď s cenami zatím
není ověřená; export tří kategorií prošel lokálním testem skutečného JavaScriptu.
Úspěch lokálních testů tyto kontroly nenahrazuje.

Konfigurace vychází z dokumentace
[REST senzorů](https://www.home-assistant.io/integrations/sensor.rest/),
[více dashboardů](https://www.home-assistant.io/dashboards/dashboards/)
a [Bubble Card](https://github.com/Clooos/Bubble-Card).
