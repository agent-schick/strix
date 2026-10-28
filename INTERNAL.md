# Náš Strix

Interní vývojová větev skutečného enginu [usestrix/strix](https://github.com/usestrix/strix).
Základ: `98e3df14258cd58d8b26d6ba8d17014c6182f755`, Strix 1.7.0, Apache-2.0.
Upstream historie, licence, engine a lokální viewer zůstávají zachované.

Vstup pro agenta je [patrik-strix](skills/patrik-strix/SKILL.md). Skill připraví
konkrétní test, řídí místní CLI a vyhodnotí jeho důkazy. Neobsahuje vlastní
modelovou smyčku. Hostovaná služba `app.strix.ai` není součástí našeho řešení.

## Lokální instalace

V pracovní větvi, s Pythonem 3.12+ a `uv`:

```bash
uv sync --frozen
STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 .venv/bin/strix --version
STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 .venv/bin/strix --help
```

Skill lze připojit do osobního adresáře skills daného agenta odkazem na
`skills/patrik-strix`. Existující skill stejného jména nejprve zkontroluj;
nepřepisuj jej. Pro Codex je cílem `~/.codex/skills/patrik-strix`.
Nová relace musí potvrdit, že jej skutečně načetla. Nastav `STRIX_CHECKOUT`
na absolutní cestu tohoto pracovního checkoutu, nebo ji agentovi sděl.

Příklad zadání po výběru modelu a cíle:

> Použij $patrik-strix pro lokální test aplikace podle připojeného issue.
> Připrav kopii cíle, použij schválený model a limity, vyhodnoť nálezy
> a po opravě zopakuj relevantní testy.

Samotná instalace nezvolí model, nepřihlásí účet ani nespustí pentest.
CLI je dostupné přes `.venv/bin/strix`; pro skutečný běh potřebuje Docker
a explicitně zvolený backend. Nativní přihlášení coding agenta není automaticky
přihlášením pro tento engine.

## Kontroly bez modelového běhu

```bash
STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 .venv/bin/python -m pytest -q \
  tests/internal/test_patrik_strix_artifacts.py \
  tests/test_cli_fail_on.py tests/test_report_writer.py \
  tests/test_e2e_budget_lifecycle.py \
  tests/test_viewer.py::test_server_serves_api_and_static \
  tests/test_viewer.py::test_run_data_requires_session
```

Tyto kontroly používají syntetická data, simulovaný runner a localhost viewer.
Ověřují integraci a zpracování výsledků, nikoli schopnost modelu najít zranitelnost.

Lokální cíle Strix připojuje zapisovatelně. Skill proto pracuje s kopií;
Docker ani instrukce ke scope samy o sobě neomezují síťové cíle.
Rozpočet je přibližný a úspěšný exit kód nezaručuje úplné pokrytí.
Výsledky a logy mohou obsahovat citlivá data; uchovávej je mimo Git.

`strix view` zobrazuje místní výsledky. Upstream viewer obsahuje také funkce
e-mailového ověření, odeslání reportu a feedbacku přes vzdálený relay;
jejich použití není nutné pro náš skill. Proměnné vypínající telemetrii
a kontrolu aktualizací nezaručují offline provoz celého enginu.

## Vlastní změny proti základu

- `skills/patrik-strix/`: interní pracovní postup a čtení artefaktů.
- `tests/internal/`: regrese čtečky výsledků.
- `tests/test_e2e_budget_lifecycle.py`: doplněný argument `skills=[]`
  ve dvou testovacích voláních podle aktuálního API enginu; původní assertions
  a testované rozpočtové chování zachovány.

Upstream aktualizace přebírej vědomě a znovu ověř CLI, schéma výsledků
a naše testy. Před publikací vlastní větve ověř vlastnictví cílového remote.
