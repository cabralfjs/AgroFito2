#!/usr/bin/env python3
"""
Atualiza o ficheiro de LMR (Limites Máximos de Resíduos) do AgroFito.

O que faz, por ordem:
  1. Descarrega o ficheiro completo de MRLs da API da Comissão Europeia
     (atualizado diariamente do lado deles).
  2. Lê os dois ficheiros de correspondência mantidos manualmente neste
     repositório:
       - culturas_crosswalk.json    (cultura SIFITO -> product_code EU)
       - substancias_crosswalk.json (substância SIFITO -> pesticide_residue_id EU)
  3. Cruza tudo e produz uma pasta lmr/ com um ficheiro JSON por cultura
     (lmr/<slug-da-cultura>.json), mais um lmr/_index.json que faz a
     correspondência entre o nome exato da cultura (tal como aparece no
     SIFITO) e o nome do ficheiro respetivo. Isto evita carregar tudo de
     uma vez no browser - o usos.html só descarrega o ficheiro da cultura
     que o utilizador está a ver, no momento em que abre o detalhe.

     Formato de cada lmr/<slug>.json:
       { "<substância SIFITO>": {"mrl": ..., "unidade": "mg/kg",
                                   "is_default": bool,
                                   "regulamento": "Regulamento (CE) n.º 396/2005",
                                   "url_regulamento": <link à versão consolidada atual>,
                                   "alteracao": <regulamento de alteração que introduziu este valor>,
                                   "url_alteracao": <link a essa alteração específica>} }

     Formato de lmr/_index.json:
       { "<cultura SIFITO>": "<slug>.json" }


Pensado para correr dentro de um GitHub Action agendado (ver
.github/workflows/update-lmr.yml) - não precisa de argumentos nem de
intervenção manual. Se a API da Comissão estiver em baixo ou mudar de
formato, o script termina com erro e o workflow falha de forma visível
(não escreve um ficheiro incompleto por cima do anterior).

Todos os ficheiros (este script e os JSON de correspondência) vivem na
raiz do repositório, junto com o index.html/produtos.html/usos.html.
"""

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR

MRL_URL = (
    "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides/"
    "pesticide-residues-mrls-download?language_code=EN&format=json&api-version=v3.0"
)
# Nota: a documentação oficial "Pesticides – APIs V3.0" da Comissão chama a
# este parâmetro "language". Na prática, a API viva exige "language_code" -
# confirmado pela mensagem de erro "Required parameter language_code
# missing." Se um dia isto voltar a falhar com 400, é o primeiro sítio a
# verificar (a Comissão pode corrigir a API para bater certo com a doc).

REQUEST_TIMEOUT = 180
MAX_RETRIES = 3

# A referência legal correta para um valor de LMR é sempre o Regulamento
# (CE) n.º 396/2005 (o regulamento-quadro que estabelece o regime de LMR na
# UE) - não o regulamento de alteração específico que introduziu aquele
# valor em concreto (ex.: "Reg. (EU) 2017/623"), que é só o veículo legal
# da alteração, não a base jurídica do LMR em si. Por isso fixamos aqui a
# referência e a ligação à versão consolidada mais recente no EUR-Lex
# (este URL sem data de consolidação mantém-se válido para sempre, a
# própria página do EUR-Lex é que vai sempre mostrar a versão atual).
REGULAMENTO_BASE = "Regulamento (CE) n.º 396/2005"
REGULAMENTO_BASE_URL = "https://eur-lex.europa.eu/legal-content/pt/TXT/?uri=CELEX%3A32005R0396"

# Alguns gateways da administração pública rejeitam (400/403) pedidos sem
# cabeçalhos de um pedido "normal" de browser. Enviamos um User-Agent e
# Accept explícitos para evitar isso - o urllib, por defeito, não os manda.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,pt;q=0.8",
}


def fetch_mrl_flat_file() -> list[dict]:
    """Descarrega o ficheiro completo de MRLs (formato JSON-lines)."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(MRL_URL, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
            records = []
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            if not records:
                raise ValueError("A API devolveu uma resposta vazia.")
            return records
        except urllib.error.HTTPError as exc:
            corpo = ""
            try:
                corpo = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:  # noqa: BLE001
                pass
            last_error = exc
            print(
                f"[aviso] tentativa {attempt}/{MAX_RETRIES} falhou: {exc}. "
                f"Resposta do servidor: {corpo!r}",
                file=sys.stderr,
            )
            time.sleep(5 * attempt)
        except Exception as exc:  # noqa: BLE001 - queremos capturar e tentar de novo
            last_error = exc
            print(f"[aviso] tentativa {attempt}/{MAX_RETRIES} falhou: {exc}", file=sys.stderr)
            time.sleep(5 * attempt)
    raise RuntimeError(f"Não foi possível descarregar o ficheiro de MRLs: {last_error}")


def load_crosswalks() -> tuple[dict, dict]:
    with open(DATA_DIR / "culturas_crosswalk.json", encoding="utf-8") as f:
        culturas = json.load(f)
    with open(DATA_DIR / "substancias_crosswalk.json", encoding="utf-8") as f:
        substancias = json.load(f)
    return culturas, substancias


def index_mrl_by_residue_and_product(records: list[dict]) -> dict:
    """
    Agrupa os registos de MRL por (pesticide_residue_id, product_code),
    guardando só a versão "Applicable" (valor atual) de cada combinação.
    Quando há mais do que um valor "Applicable" para o mesmo par (não
    devia acontecer, mas os dados de origem já mostraram inconsistências
    pontuais), fica o mais recente por application_date.
    """
    index: dict[tuple[int, str], dict] = {}
    for rec in records:
        if rec.get("applicability_text") != "Applicable":
            continue
        key = (rec.get("pesticide_residue_id"), rec.get("product_code"))
        existing = index.get(key)
        if existing is None or (rec.get("application_date") or "") > (existing.get("application_date") or ""):
            index[key] = rec
    return index


def parse_mrl_value(raw_value: str) -> tuple[float | None, bool]:
    """
    Devolve (valor_numerico, is_default). O ficheiro da UE marca os
    valores por defeito (limite de determinação, sem ensaio específico
    para esta combinação) com um asterisco, ex.: "0.01*".
    """
    if raw_value is None:
        return None, False
    is_default = "*" in raw_value
    cleaned = raw_value.replace("*", "").strip()
    try:
        return float(cleaned), is_default
    except ValueError:
        return None, is_default


def build_lmr_data(culturas: dict, substancias: dict, mrl_index: dict) -> dict:
    output: dict[str, dict] = {}
    stats = {"combinacoes": 0, "com_valor": 0, "sem_valor": 0}

    for cultura_nome, cultura_info in culturas.items():
        product_codes = cultura_info.get("product_codes") or []
        if not product_codes:
            continue

        cultura_result: dict[str, dict] = {}

        for substancia_nome, substancia_info in substancias.items():
            residue_id = substancia_info.get("pesticide_residue_id")
            if residue_id is None:
                continue  # substância sem definição de resíduo (ex.: safener) - sem LMR aplicável

            # uma cultura pode mapear para mais do que um product_code
            # (ex.: rabanete -> raiz + folhas); guardamos todos os valores
            # encontrados, identificados pelo nome do produto EU.
            valores_encontrados = []
            for code in product_codes:
                rec = mrl_index.get((residue_id, code))
                if rec is None:
                    continue
                valor, is_default = parse_mrl_value(rec.get("mrl_value_only") or rec.get("mrl_value"))
                if valor is None:
                    continue
                valores_encontrados.append({
                    "produto_eu": rec.get("product_name"),
                    "mrl": valor,
                    "unidade": "mg/kg",
                    "is_default": is_default,
                    "regulamento": REGULAMENTO_BASE,
                    "url_regulamento": REGULAMENTO_BASE_URL,
                    "alteracao": rec.get("regulation_number"),
                    "url_alteracao": rec.get("regulation_url"),
                })

            stats["combinacoes"] += 1
            if valores_encontrados:
                stats["com_valor"] += 1
                cultura_result[substancia_nome] = (
                    valores_encontrados[0] if len(valores_encontrados) == 1 else valores_encontrados
                )
            else:
                stats["sem_valor"] += 1

        if cultura_result:
            output[cultura_nome] = cultura_result

    print(
        f"[info] combinações cultura×substância avaliadas: {stats['combinacoes']} | "
        f"com valor de LMR: {stats['com_valor']} | sem correspondência: {stats['sem_valor']}",
        file=sys.stderr,
    )
    return output


def slugify(nome: str) -> str:
    """
    Converte um nome de cultura num nome de ficheiro seguro: sem acentos,
    minúsculas, só letras/números/hífens. Ex.: "Couve-de-Bruxelas" ->
    "couve-de-bruxelas"; "Aipo (folhas e caules)" -> "aipo-folhas-e-caules".
    """
    sem_acentos = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acentos).strip("-").lower()
    return slug or "cultura"


def write_output_files(lmr_data: dict) -> None:
    """
    Escreve um ficheiro JSON por cultura dentro de lmr/, mais o índice
    lmr/_index.json que liga o nome exato da cultura (como está no SIFITO)
    ao nome do ficheiro. Usa nomes de ficheiro únicos mesmo que duas
    culturas dessem o mesmo slug (acrescenta um número).
    """
    lmr_dir = BASE_DIR / "lmr"
    lmr_dir.mkdir(exist_ok=True)

    index: dict[str, str] = {}
    slugs_usados: dict[str, int] = {}

    for cultura_nome, substancias_info in lmr_data.items():
        base_slug = slugify(cultura_nome)
        contagem = slugs_usados.get(base_slug, 0)
        slugs_usados[base_slug] = contagem + 1
        slug = base_slug if contagem == 0 else f"{base_slug}-{contagem + 1}"
        nome_ficheiro = f"{slug}.json"

        with open(lmr_dir / nome_ficheiro, "w", encoding="utf-8") as f:
            json.dump(substancias_info, f, ensure_ascii=False, separators=(",", ":"))

        index[cultura_nome] = nome_ficheiro

    with open(lmr_dir / "_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1, sort_keys=True)

    tamanho_total = sum((lmr_dir / p).stat().st_size for p in index.values())
    print(
        f"[info] {len(index)} ficheiros gerados em {lmr_dir} "
        f"({tamanho_total / 1024:.0f} KB no total, maior ficheiro individual "
        f"muito mais pequeno que isso).",
        file=sys.stderr,
    )


def main() -> None:
    print("[info] a descarregar ficheiro de MRLs da Comissão Europeia...", file=sys.stderr)
    records = fetch_mrl_flat_file()
    print(f"[info] {len(records)} linhas recebidas.", file=sys.stderr)

    culturas, substancias = load_crosswalks()
    mrl_index = index_mrl_by_residue_and_product(records)

    lmr_data = build_lmr_data(culturas, substancias, mrl_index)
    write_output_files(lmr_data)


if __name__ == "__main__":
    main()
