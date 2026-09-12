#!/usr/bin/env python3
"""
Atualiza o ficheiro de LMR (Limites Máximos de Resíduos) do AgroFito.

O que faz, por ordem:
  1. Descarrega o ficheiro completo de MRLs da API da Comissão Europeia
     (atualizado diariamente do lado deles).
  2. Lê os dois ficheiros de correspondência mantidos manualmente neste
     repositório:
       - data/culturas_crosswalk.json   (cultura SIFITO -> product_code EU)
       - data/substancias_crosswalk.json (substância SIFITO -> pesticide_residue_id EU)
  3. Cruza tudo e produz data/lmr_data.json, no formato:
       { "<cultura SIFITO>": { "<substância SIFITO>": {"mrl": ..., "unidade": "mg/kg",
                                                          "is_default": bool,
                                                          "regulamento": ..., "url": ...} } }

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
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR

MRL_URL = (
    "https://api.datalake.sante.service.ec.europa.eu/sante/pesticides/"
    "pesticide-residues-mrls-download?language=PT&format=json&api-version=v3.0"
)

REQUEST_TIMEOUT = 120
MAX_RETRIES = 3


def fetch_mrl_flat_file() -> list[dict]:
    """Descarrega o ficheiro completo de MRLs (formato JSON-lines)."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(MRL_URL, headers={"Accept": "application/json"})
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
                    "regulamento": rec.get("regulation_number"),
                    "url_regulamento": rec.get("regulation_url"),
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


def main() -> None:
    print("[info] a descarregar ficheiro de MRLs da Comissão Europeia...", file=sys.stderr)
    records = fetch_mrl_flat_file()
    print(f"[info] {len(records)} linhas recebidas.", file=sys.stderr)

    culturas, substancias = load_crosswalks()
    mrl_index = index_mrl_by_residue_and_product(records)

    lmr_data = build_lmr_data(culturas, substancias, mrl_index)

    output_path = DATA_DIR / "lmr_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(lmr_data, f, ensure_ascii=False, separators=(",", ":"))

    print(f"[info] ficheiro gerado: {output_path} ({output_path.stat().st_size} bytes)", file=sys.stderr)


if __name__ == "__main__":
    main()
