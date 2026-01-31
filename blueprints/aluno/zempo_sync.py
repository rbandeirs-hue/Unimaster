# ======================================================
# Sync currículo Zempo → aluno_competicoes / aluno_eventos
# ======================================================
# Requer: link_zempo do aluno. Credenciais: zempo_user/zempo_pass no form ou env.
# Login: tenta portal e index.php.
# ======================================================

from __future__ import annotations

import os
import re
import unicodedata
from typing import List, Dict, Any, Tuple
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

ZEMPO_BASE = "https://zempo.com.br"
ZEMPO_PORTAL = "https://zempo.com.br/portal/"
ZEMPO_LOGIN = "https://zempo.com.br/index.php"


def _normalize(text: str) -> str:
    """Remove acentos para matching flexível."""
    if not text:
        return ""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").upper()


def _session_fetch_profile(link_zempo: str, zempo_user: str = None, zempo_pass: str = None) -> Tuple[bool, str, str]:
    """
    Login (se credenciais), GET profile, return (ok, html, error_message).
    Credenciais: zempo_user/zempo_pass ou ZEMPO_USER/ZEMPO_PASS em env.
    """
    if not HAS_DEPS:
        return False, "", "Dependências 'requests' e 'beautifulsoup4' não instaladas."

    user = (zempo_user or os.environ.get("ZEMPO_USER", "") or "").strip()
    senha = (zempo_pass or os.environ.get("ZEMPO_PASS", "") or "").strip()
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    })

    if user and senha:
        logged = False
        for login_url in (ZEMPO_PORTAL, ZEMPO_LOGIN, ZEMPO_BASE + "/index.php?secao=login"):
            try:
                r = s.get(login_url, timeout=15)
                r.raise_for_status()
            except Exception as e:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for form in soup.find_all("form"):
                inputs = {inp.get("name"): inp.get("value") or "" for inp in form.find_all("input", {"name": True}) if inp.get("name")}
                user_key = next((k for k in ("usuario", "login", "user", "email", "codigo") if k in inputs), None)
                pass_key = next((k for k in ("senha", "password", "pass") if k in inputs), None)
                if user_key and pass_key:
                    inputs[user_key] = user
                    inputs[pass_key] = senha
                    action = form.get("action") or ""
                    action_url = urljoin(ZEMPO_BASE, action) if action else login_url
                    try:
                        s.post(action_url, data=inputs, timeout=15, allow_redirects=True)
                        logged = True
                        break
                    except Exception:
                        pass
            if logged:
                break

    if not link_zempo.strip().startswith("http"):
        link_zempo = urljoin(ZEMPO_BASE, link_zempo)
    try:
        r = s.get(link_zempo, timeout=15)
        r.raise_for_status()
        return True, r.text, ""
    except Exception as e:
        return False, "", f"Não foi possível acessar o link do perfil: {e!s}"


def _cell_text(cell) -> str:
    """Extrai texto da célula, incluindo title/alt de img."""
    img = cell.find("img")
    if img:
        t = img.get("title") or img.get("alt") or ""
        if t:
            return t.strip()
    return (cell.get_text() or "").strip()


def _map_colocacao(raw: str) -> str:
    """Mapeia ouro→1º Lugar, prata→2º Lugar, bronze→3º Lugar."""
    r = (raw or "").strip().lower()
    if r == "ouro":
        return "1º Lugar"
    if r == "prata":
        return "2º Lugar"
    if r == "bronze":
        return "3º Lugar"
    return raw.strip() if raw else ""


def _parse_competicoes(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Extrai lista de competições. Estrutura Zempo: td 'PARTICIPAÇÕES EM COMPETIÇÕES - ATLETA' -> table com th colocação, competição, âmbito, local, data, categoria."""
    out = []
    for tag in soup.find_all(["td", "th", "h2", "h3", "h4", "h5", "strong", "b", "div", "span"]):
        text = _normalize(tag.get_text() or "")
        if "PARTICIPACOES" in text and "COMPETICOES" in text and "ATLETA" in text and "STAFF" not in text:
            cont = tag.find_next("table")
            if not cont:
                continue
            rows = cont.find_all("tr")
            for i, row in enumerate(rows):
                cells = row.find_all(["td", "th"])
                if len(cells) < 5:
                    continue
                first_text = _cell_text(cells[0]).strip() if cells else ""
                if first_text.isdigit() and len(first_text) == 4:
                    continue
                hdr = _normalize(first_text + " ".join(_cell_text(c) for c in cells[:5]))
                if "COLOCACAO" in hdr or "COMPETICAO" in hdr:
                    continue
                raw_coloc = _cell_text(cells[0]) if len(cells) > 0 else ""
                colocacao = _map_colocacao(raw_coloc)
                competicao = _cell_text(cells[1]) if len(cells) > 1 else ""
                ambito = _cell_text(cells[2]) if len(cells) > 2 else ""
                local = _cell_text(cells[3]) if len(cells) > 3 else ""
                data_s = (_cell_text(cells[4]) if len(cells) > 4 else "").split("a")[0].strip()
                categoria = _cell_text(cells[5]) if len(cells) > 5 else ""
                data_parsed = None
                if data_s:
                    for fmt in (r"(\d{2}/\d{2}/\d{4})", r"(\d{4}-\d{2}-\d{2})", r"(\d{2}-\d{2}-\d{4})"):
                        m = re.search(fmt, data_s)
                        if m:
                            try:
                                from datetime import datetime
                                s = m.group(1)
                                if "-" in s and len(s) == 10 and s[4] == "-":
                                    data_parsed = datetime.strptime(s, "%Y-%m-%d").date()
                                elif "-" in s:
                                    data_parsed = datetime.strptime(s, "%d-%m-%Y").date()
                                elif "/" in s:
                                    data_parsed = datetime.strptime(s, "%d/%m/%Y").date()
                            except Exception:
                                pass
                            break
                out.append({
                    "colocacao": colocacao, "competicao": competicao, "ambito": ambito,
                    "local_texto": local, "data_competicao": data_parsed, "categoria": categoria, "ordem": len(out),
                })
            if out:
                break
    if not out:
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
            hnorm = _normalize(" ".join(headers))
            if "COLOCACAO" in hnorm and ("COMPETICAO" in hnorm or "COMPETIÇÃO" in hnorm.upper()):
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"])
                    texts = [c.get_text(strip=True) for c in cells]
                    if len(texts) >= 2:
                        raw_coloc = texts[0] if len(texts) > 0 else ""
                        out.append({
                            "colocacao": _map_colocacao(raw_coloc),
                            "competicao": texts[1] if len(texts) > 1 else "",
                            "ambito": texts[2] if len(texts) > 2 else "",
                            "local_texto": texts[3] if len(texts) > 3 else "",
                            "data_competicao": None,
                            "categoria": texts[5] if len(texts) > 5 else "",
                            "ordem": len(out),
                        })
                break
    return out


def _parse_eventos(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Extrai lista de eventos. Estrutura Zempo: td 'PARTICIPAÇÕES EM EVENTOS' -> table com evento, atividade, âmbito, local, data."""
    out = []
    for tag in soup.find_all(["td", "th", "h2", "h3", "h4", "h5", "strong", "b", "div", "span"]):
        text = _normalize(tag.get_text() or "")
        if ("PARTICIPACOES" in text or "PARTICIPA" in text.upper()) and "EVENTOS" in text and "COMPETICOES" not in text and "STAFF" not in text:
            cont = tag.find_next("table")
            if not cont:
                continue
            rows = cont.find_all("tr")
            for i, row in enumerate(rows):
                cells = row.find_all(["td", "th"])
                if len(cells) < 5:
                    continue
                first_text = _cell_text(cells[0]).strip() if cells else ""
                if first_text.isdigit() and len(first_text) == 4:
                    continue
                hdr = _normalize(first_text + " ".join(_cell_text(c) for c in cells[:3]))
                if "EVENTO" in hdr and "ATIVIDADE" in hdr:
                    continue
                texts = [_cell_text(c) for c in cells]
                if not any(t for t in texts):
                    continue
                evento = texts[0] if len(texts) > 0 else ""
                atividade = texts[1] if len(texts) > 1 else ""
                ambito = texts[2] if len(texts) > 2 else ""
                local = texts[3] if len(texts) > 3 else ""
                data_s = (texts[4] if len(texts) > 4 else "").split("a")[0].strip()
                data_parsed = None
                if data_s:
                    for fmt in (r"(\d{2}/\d{2}/\d{4})", r"(\d{4}-\d{2}-\d{2})", r"(\d{2}-\d{2}-\d{4})"):
                        m = re.search(fmt, data_s)
                        if m:
                            try:
                                from datetime import datetime
                                s = m.group(1)
                                if "-" in s and len(s) == 10 and s[4] == "-":
                                    data_parsed = datetime.strptime(s, "%Y-%m-%d").date()
                                elif "-" in s:
                                    data_parsed = datetime.strptime(s, "%d-%m-%Y").date()
                                elif "/" in s:
                                    data_parsed = datetime.strptime(s, "%d/%m/%Y").date()
                            except Exception:
                                pass
                            break
                out.append({
                    "evento": evento, "atividade": atividade, "ambito": ambito,
                    "local_texto": local, "data_evento": data_parsed, "ordem": i,
                })
            if out:
                break
    if not out:
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True).upper() for th in table.find_all("th")]
            hnorm = _normalize(" ".join(headers))
            if "EVENTO" in hnorm and ("ATIVIDADE" in hnorm or "DATA" in hnorm):
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"])
                    texts = [c.get_text(strip=True) for c in cells]
                    if len(texts) >= 1:
                        data_parsed = None
                        if len(texts) >= 5:
                            for fmt in (r"\d{2}/\d{2}/\d{4}", r"\d{4}-\d{2}-\d{2}", r"\d{2}-\d{2}-\d{4}"):
                                m = re.search(fmt, texts[4])
                                if m:
                                    try:
                                        from datetime import datetime
                                        s = m.group(0)
                                        if "-" in s and len(s) == 10 and s[4] == "-":
                                            data_parsed = datetime.strptime(s, "%Y-%m-%d").date()
                                        elif "/" in s:
                                            data_parsed = datetime.strptime(s, "%d/%m/%Y").date()
                                    except Exception:
                                        pass
                                    break
                        out.append({
                            "evento": texts[0] if len(texts) > 0 else "",
                            "atividade": texts[1] if len(texts) > 1 else "",
                            "ambito": texts[2] if len(texts) > 2 else "",
                            "local_texto": texts[3] if len(texts) > 3 else "",
                            "data_evento": data_parsed,
                            "ordem": len(out),
                        })
                break
    return out


def sync_zempo_curriculo(aluno_id: int, link_zempo: str, zempo_user: str = None, zempo_pass: str = None) -> Tuple[bool, str]:
    """
    Sincroniza currículo do Zempo para aluno_competicoes e aluno_eventos.
    Retorna (sucesso, mensagem).
    zempo_user/zempo_pass opcionais (ou use ZEMPO_USER, ZEMPO_PASS em env).
    """
    if not link_zempo or not link_zempo.strip():
        return False, "Informe o link do perfil Zempo."
    if not HAS_DEPS:
        return False, "Dependências para sincronização não instaladas (requests, beautifulsoup4)."

    ok, html, err = _session_fetch_profile(link_zempo.strip(), zempo_user=zempo_user, zempo_pass=zempo_pass)
    if not ok:
        return False, err or "Não foi possível acessar a página do Zempo."

    soup = BeautifulSoup(html, "html.parser")
    competicoes = _parse_competicoes(soup)
    eventos = _parse_eventos(soup)

    from config import get_db_connection
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM aluno_competicoes WHERE aluno_id = %s", (aluno_id,))
        for c in competicoes:
            cur.execute(
                """INSERT INTO aluno_competicoes (aluno_id, colocacao, competicao, ambito, local_texto, data_competicao, categoria, ordem)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (aluno_id, c.get("colocacao") or None, c.get("competicao") or None, c.get("ambito") or None,
                 c.get("local_texto") or None, c.get("data_competicao"), c.get("categoria") or None, c.get("ordem", 0)),
            )
        cur.execute("DELETE FROM aluno_eventos WHERE aluno_id = %s", (aluno_id,))
        for e in eventos:
            cur.execute(
                """INSERT INTO aluno_eventos (aluno_id, evento, atividade, ambito, local_texto, data_evento, ordem)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (aluno_id, e.get("evento") or None, e.get("atividade") or None, e.get("ambito") or None, e.get("local_texto") or None, e.get("data_evento"), e.get("ordem", 0)),
            )
        conn.commit()
    except Exception as ex:
        conn.rollback()
        return False, f"Erro ao gravar currículo: {ex!s}"
    finally:
        cur.close()
        conn.close()

    n_c, n_e = len(competicoes), len(eventos)
    msg = f"Sincronização concluída: {n_c} competição(ões) e {n_e} evento(s) importados."
    if n_c == 0 and n_e == 0:
        msg += " Nenhum dado encontrado na página. Verifique: 1) se o link é do perfil correto; 2) se informou código e senha Zempo; 3) se a página exibe as seções 'Participações em competições' e 'Participações em eventos' quando acessada no navegador."
    return True, msg
