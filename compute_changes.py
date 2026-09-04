#!/usr/bin/env python3
"""
AgroFito — compute_changes.py

Compara os ficheiros JSON recém-actualizados (já no disco, gerados pelo
update_sifito.py / update_produtos.py) com a versão anterior, ainda
disponível no commit anterior (git HEAD), e produz um resumo em
alteracoes.json — usado pelo site para mostrar o painel "O que mudou".

Não depende de nenhum histórico externo: só do git do próprio repositório.
Corre DEPOIS de update_sifito.py e update_produtos.py, e ANTES do commit.
"""
import json
import subprocess
from datetime import datetime, timezone

USOS_FILES = [
    "data_autorizadas.json",
    "data_canceladas_venda_permitida.json",
    "data_canceladas_venda_interdita_util_permitida.json",
    "data_canceladas_venda_util_interditas.json",
]
PRODUTOS_FILES = [
    "prod_autorizadas.json",
    "prod_canceladas_venda_permitida.json",
    "prod_canceladas_venda_interdita_util_permitida.json",
    "prod_canceladas_venda_util_interditas.json",
]


def git_show_old(filename):
    """Devolve o conteúdo do ficheiro tal como estava no commit anterior
    (HEAD, antes das alterações desta run). Se o ficheiro não existia
    ainda (ex.: primeira vez que o workflow corre), devolve None."""
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{filename}"],
            capture_output=True, text=True, check=True,
        )
        return out.stdout
    except subprocess.CalledProcessError:
        return None


def load_records(filename, from_disk=False):
    """Carrega os registos de um ficheiro — do disco (versão nova) ou do
    git HEAD (versão antiga)."""
    if from_disk:
        try:
            with open(filename, encoding="utf-8") as f:
                raw = f.read()
        except FileNotFoundError:
            return []
    else:
        raw = git_show_old(filename)
        if raw is None:
            return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data.get("records", [])


def usos_key(r):
    """Identificador estável de um registo de Condições de Utilização —
    tem de corresponder à mesma lógica usada no lado do browser (fidOf
    em usos.html), para os dois lados falarem da mesma coisa."""
    return "|".join([
        str(r.get("numero", "")),
        str(r.get("cultura", "")),
        str(r.get("inimigo", "")),
        str(r.get("produto", "")),
        str(r.get("dose", "")),
    ])


def produtos_key(r):
    """Identificador estável de um registo de Produtos Fitofarmacêuticos —
    espelha fidOf em produtos.html."""
    return "|".join([
        str(r.get("numero", "")),
        str(r.get("designacao", "")),
        str(r.get("titular", "")),
    ])


def diff_app(files, key_fn, label_fn):
    """Compara os registos antigos vs novos de um conjunto de ficheiros
    (uma "app": usos ou produtos), e devolve um resumo das transições
    de estado."""
    old_by_key = {}
    new_by_key = {}

    for fn in files:
        for r in load_records(fn, from_disk=False):
            old_by_key[key_fn(r)] = r
        for r in load_records(fn, from_disk=True):
            new_by_key[key_fn(r)] = r

    novas_canceladas = []   # Autorizada → Cancelada (o mais importante)
    reativadas = []         # Cancelada → Autorizada (mais raro, mas relevante)
    novos_registos = []     # não existia antes, apareceu agora
    removidos = []          # existia antes, desapareceu por completo

    for k, new_r in new_by_key.items():
        old_r = old_by_key.get(k)
        if old_r is None:
            novos_registos.append(new_r)
            continue
        old_estado = old_r.get("estado", "")
        new_estado = new_r.get("estado", "")
        if old_estado == new_estado:
            continue
        item = {"label": label_fn(new_r), "de": old_estado, "para": new_estado}
        if old_estado == "Autorizada" and new_estado != "Autorizada":
            novas_canceladas.append(item)
        elif old_estado != "Autorizada" and new_estado == "Autorizada":
            reativadas.append(item)

    for k, old_r in old_by_key.items():
        if k not in new_by_key:
            removidos.append(old_r)

    return {
        "novas_canceladas": len(novas_canceladas),
        "reativadas": len(reativadas),
        "novos_registos": len(novos_registos),
        "removidos": len(removidos),
        "detalhe_canceladas": novas_canceladas[:50],  # limite de segurança
        "detalhe_reativadas": reativadas[:50],
    }


def main():
    usos_label = lambda r: f'{r.get("produto","—")} · {r.get("cultura","—")} · {r.get("inimigo","—")}'
    produtos_label = lambda r: f'{r.get("designacao","—")} ({r.get("titular","—")})'

    resultado = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usos": diff_app(USOS_FILES, usos_key, usos_label),
        "produtos": diff_app(PRODUTOS_FILES, produtos_key, produtos_label),
    }

    with open("alteracoes.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print("alteracoes.json gerado:")
    print(f'  usos: {resultado["usos"]["novas_canceladas"]} novas canceladas, '
          f'{resultado["usos"]["reativadas"]} reativadas')
    print(f'  produtos: {resultado["produtos"]["novas_canceladas"]} novas canceladas, '
          f'{resultado["produtos"]["reativadas"]} reativadas')


if __name__ == "__main__":
    main()
