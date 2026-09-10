# Lokální kontroly konfigurace

## Rozhodnutí z 2026-09-09

Před každým commitem musí projít kontrola všech verzovaných YAML souborů,
nových neignorovaných YAML souborů a celá lokální sada testů. Kontrola pouze
změněného souboru nestačí. Po další úpravě se kontrola opakuje. Pravidlo platí
i pro commity dokumentace; nezakládá oprávnění ke commitu ani nasazení.

## Jednorázová příprava v každém worktree

Je potřeba Python 3.12 nebo novější, Git a Node.js 18 nebo novější v PATH.
Node.js spouští původní JavaScript exportéru cen paliv proti lokálním náhradám
Google služeb; nic se neposílá do sítě. Z kořene worktree na Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
```

Pokud Python není v PATH, první příkaz spusť úplnou cestou k jeho instalaci.
Balíčky se instalují do místního prostředí; příští kontroly už nic nestahují.
Prostředí `.venv` se neverzuje.

## Před každým commitem

```powershell
.\.venv\Scripts\python.exe tools/check.py
```

Na Linuxu nebo macOS použij `.venv/bin/python`. S aktivovaným prostředím
stačí `python tools/check.py`. Příkaz vrací nenulový návratový kód při chybě
YAML, testu nebo prázdné sadě testů. Výsledek zaznamenej do popisu commitu.
Pravidlo je závazné v `AGENTS.md`; automatický Git hook zatím není instalovaný.

## Co kontrolujeme

- PyYAML: syntaxi a duplicitní klíče ve všech YAML souborech vybraných Gitem.
  Nevyžadujeme změnu stylu odsazení ani zkracování existujících řádků.
- Značky HA `!include`, jeho adresářové varianty, `!secret` a `!env_var` se
  rozpoznávají jako odkazy. Tajné hodnoty ani proměnné prostředí se nenačítají.
- Chybějící include se hlásí jako upozornění. Repozitář není úplná instalace;
  aktuálně chybí adresář `themes`. Jeho obsah se nevymýšlí ani nenahrazuje.
- Testy ověřují parser, výběr souborů, zapojení balíčku FVE a zachování všech
  38 ID migrovaných entit. Kontrolují syntaxi moderních šablon a odmítnou návrat
  `platform: template` u entit v kterémkoliv YAML souboru; platné template
  triggery automatizací zůstávají povolené.
- Chování `binary_sensor.fve_vybijeni_baterie` ověřujeme pro 64 kombinací
  stavů vstupů včetně `unknown` a `unavailable`. Další testy hlídají akce a stavy
  všech sedmi přepínačů termostatů a dostupnost i 20% rezervu energie baterie.
- Ceny paliv: všechny cenové šablony při chybějících a neplatných vstupech,
  vazbu 16 nabídek na dashboard, export tří kategorií, odmítnutí nesprávného
  tokenu a rozlišení nulové a chybějící desetidenní změny.
  JavaScript exportéru a formátování karet se vykonává v Node.js
  s místními náhradami služeb Google a DOM, bez přístupu do sítě.

Testy šablon používají skutečný Jinja engine a náhrady použitých funkcí HA nad
testovacími daty. Netestují aktualizace entit, časování, souběhy automatizací,
obnovu po restartu ani skutečný měnič. Ostatní automatizace zatím mají kontrolu
YAML, nikoli testy chování. Při změně jejich logiky přidávej cílené testy
z doložených požadavků, zejména pro hranice a nedostupná data.

## Úplná kontrola schémat Home Assistanta

Samotný parser neověřuje povolené položky integrací. K tomu slouží oficiální
[`check_config`](https://www.home-assistant.io/docs/tools/check_config/):

```text
hass --script check_config -c CESTA_KE_KOPII_KONFIGURACE
```

Pro budoucí místní kontrolu lze připravit izolovaný Linux kontejner s přesnou
verzí cílového HA, potřebnými vlastními integracemi a úplnou kopií konfigurace.
Spouštět pouze `check_config`, bez sítě a bez běžného startu HA. Nepřipojovat
provozní adresář pro zápis a nevypisovat tajné hodnoty. Verzi HA ani chybějící
soubory nedoplňovat odhadem. Toto prostředí zatím není připravené; zelená lokální
kontrola tedy neznamená úplnou validaci HA ani připravenost k nasazení.
