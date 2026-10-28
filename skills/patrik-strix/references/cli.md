# Lokální CLI

Ověřeno proti Strix 1.7.0, upstream `98e3df14258cd58d8b26d6ba8d17014c6182f755`. Při aktualizaci zkontroluj skutečný `--help` a schéma artefaktů. Pro tento workflow se nepoužívá `strix cloud` ani automatická instalace upstream cloud skillů.

## Preflight bez modelového požadavku

`STRIX_CHECKOUT` je absolutní cesta k ověřenému pracovnímu checkoutu našeho forku, s lokální `.venv` vytvořenou ze zamčených závislostí. Není-li nastavená, zjisti ji z aktuálního projektu; nepředpokládej umístění podle instalace skillu. Příklad předpokládá Bash a již nastavenou cestu:

```bash
test -n "${STRIX_CHECKOUT:-}" && test -x "$STRIX_CHECKOUT/.venv/bin/strix"
git -C "$STRIX_CHECKOUT" rev-parse HEAD
STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 "$STRIX_CHECKOUT/.venv/bin/strix" --version
STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 "$STRIX_CHECKOUT/.venv/bin/strix" --help
docker info --format '{{.ServerVersion}}'
```

Ověř model, endpoint a příslušný credential mechanismus proti zadání bez výpisu hodnot klíčů. Tato kontrola neprokazuje dostupnost modelu; síťový warm-up patří až k autorizovanému scanu. Není-li prostředí připravené, lze v checkoutu instalovat jeho zamčené lokální závislosti (`uv sync --frozen`) v rámci oprávnění projektu. Nedělej `--update` a neměň model jako reakci na chybu.

Obě env proměnné vypínají telemetrii enginu a kontrolu aktualizace pro daný proces. Nejde o režim bez sítě: model, sandbox pull, test cíle a některé funkce vieweru mají vlastní síťová spojení.

## Nový běh

Nejdřív připrav oddělené cesty:

- `STRIX_TARGET_COPY`: absolutní cesta k již prověřené kopii cíle, se zaznamenaným snapshotem.
- `STRIX_RUN_WORKDIR`: samostatný pracovní adresář pro konkrétní test mimo cílovou kopii. Strix pod aktuálním adresářem vytvoří `strix_runs/<vygenerovaný-název>/`, včetně `.state` pro resume.
- `STRIX_INSTRUCTION_FILE`: soubor s potvrzeným zadáním bez produkčních tajných údajů.
- `STRIX_CONFIG_FILE`: samostatný konfigurační soubor pro běh mimo Git i cílovou kopii, při založení s obsahem `{"env":{}}` a oprávněním `0600`. Tím se nepřevezme osobní `~/.strix/cli-config.json`. Strix do něj při běhu může uložit nastavené env credentials; nezveřejňuj jej, nepřidávej do checkpointu ani do kopie cíle. Credentials nastav jen autorizovaným mechanismem projektu. Pro resume zachovej odpovídající chráněnou konfiguraci.
- `STRIX_LLM`, `STRIX_BUDGET_USD`, `STRIX_MAX_TURNS`, `STRIX_SCAN_MODE`: konkrétní zvolené hodnoty z briefu, žádné nové implicitní schválení. Backend/credentials nastav ověřeným mechanismem projektu.

Bez MCP vytvoř v run adresáři `mcp-none.json` s obsahem `[]`. Tím se pro tento běh nepřevezme osobní `~/.strix/mcp-servers.json`. Pokud zadání vyžaduje MCP, místo toho použij jeho ověřený konfigurační soubor s povolenými nástroji; neoznačuj přeskočený server za úspěšně použitý.

Po ověření všech hodnot spusť z run adresáře:

```bash
cd "$STRIX_RUN_WORKDIR"
STRIX_LLM="${STRIX_LLM:?Vyber model podle briefu}" \
  STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 \
  "$STRIX_CHECKOUT/.venv/bin/strix" -n \
  --config "$STRIX_CONFIG_FILE" \
  --target "$STRIX_TARGET_COPY" \
  --scope-mode full \
  --scan-mode "$STRIX_SCAN_MODE" \
  --instruction-file "$STRIX_INSTRUCTION_FILE" \
  --mcp-config "$STRIX_RUN_WORKDIR/mcp-none.json" \
  --max-budget "$STRIX_BUDGET_USD" \
  --max-turns "$STRIX_MAX_TURNS"
```

Pro diff test nahraď `--scope-mode full` parametry `--scope-mode diff --diff-base "$STRIX_DIFF_BASE"`, kde base je ověřený commit přítomný v kopii. Pro schválený vzdálený test nahraď pouze target přesným schváleným URL; oprávnění lokálního snapshotu se na URL nepřenáší. Návratový kód zachyť i při běhu na pozadí: `2` znamená nález podle zvoleného `--fail-on`, `1` chybu; `0` neprokazuje dokončené pokrytí. V logu může být citlivý obsah, proto jej nezveřejňuj celý.

Engine generuje jméno běhu sám; tento upstream nemá veřejný přepínač `--run-name`. Zaznamenej konkrétní výstupní cestu procesu, ne „nejnovější adresář“ ze sdíleného prostoru.

## Artefakty a resume

`STRIX_SKILL_DIR` je skutečný adresář načteného skillu (pro pomocný skript), `STRIX_RUN_DIR` přesná výstupní cesta ukončeného běhu:

```bash
python3 "$STRIX_SKILL_DIR/scripts/inspect_run.py" "$STRIX_RUN_DIR" \
  --max-budget "$STRIX_BUDGET_USD"
```

Pomocník pracuje jen se soubory, nic nespouští a nevypisuje obsah instrukcí, PoC ani credentials. Čte `run.json`, případný index nálezů, report a `coverage.json`; vrací jejich hashe a konzervativní souhrn. Návratové kódy jsou vlastní: `0` = zaznamenané dokončení vyžaduje posouzení pokrytí, `3` = neúplný běh/podklady, `2` = nečitelné nebo neplatné artefakty. Žádný kód není bezpečnostní verdikt. Chybějící index nálezů zůstává neznámým počtem. Hash je identifikace přečtených bajtů, ne důkaz pravdivosti reportu ani atomický snapshot živého běhu.

Report může obsahovat tvrzení o úplnosti po varování o rozpočtu; porovnej je s logem, coverage a skutečně provedenými testy. `coverage.completeness.complete: true` je záznam enginu, ne nezávislé ověření pokrytí zadání.

Resume používej pouze pro tentýž cíl, snapshot a stále platné oprávnění; z původního `STRIX_RUN_WORKDIR`, s přesným vygenerovaným názvem a stejným ověřeným backendem:

```bash
STRIX_LLM="${STRIX_LLM:?Pouzij model puvodniho behu}" \
  STRIX_TELEMETRY=0 STRIX_NO_UPDATE_CHECK=1 \
  "$STRIX_CHECKOUT/.venv/bin/strix" -n --resume "$STRIX_RUN_NAME" \
  --config "$STRIX_CONFIG_FILE" \
  --mcp-config "$STRIX_RUN_WORKDIR/mcp-none.json" \
  --max-budget "$STRIX_BUDGET_USD" --max-turns "$STRIX_MAX_TURNS"
```

Resume obnovuje historii i dosažené náklady; nejde o novou rozpočtovou obálku. Nepřidávej `--target`. Předem zachovej původní hashe a po doběhu je přepočítej. Pro jiný commit použij nový běh.

Lokální viewer (`strix view`) je volitelný. Čtení artefaktů přes pomocník nevyžaduje účet. Viewer má také funkce s OTP, odesláním reportu a feedbackem přes vzdálenou službu; jejich použití není součástí lokální kontroly a vyžaduje oprávnění pro daný přenos.
