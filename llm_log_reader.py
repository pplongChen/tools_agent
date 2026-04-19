import re
import html as html_lib
import difflib
import uuid
import base64
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── 檔案標頭清理與合併邏輯 ──────────────────────────────────────────

def extract_header(content: str) -> str:
    """擷取檔案開頭的 Session 標頭資訊"""
    lines = content.split('\n')
    for i, line in enumerate(lines[:15]):
        if line.strip() == '---':
            header_text = '\n'.join(lines[:i])
            if 'Session ID:' in header_text or 'Created:' in header_text:
                return header_text.strip()
                
    if len(lines) > 5 and ('Session ID:' in '\n'.join(lines[:6])):
        return '\n'.join(lines[:6]).strip()
        
    return ""

def clean_header(content: str) -> str:
    """刪除檔案開頭的 Session ID 等 metadata 資訊，以便進行純對話解析"""
    lines = content.split('\n')
    for i, line in enumerate(lines[:15]):
        if line.strip() == '---':
            header_text = '\n'.join(lines[:i])
            if 'Session ID:' in header_text or 'Created:' in header_text:
                return '\n'.join(lines[i+1:]).strip()
    
    if len(lines) > 5 and ('Session ID:' in '\n'.join(lines[:6])):
        return '\n'.join(lines[6:]).strip()
        
    return content

def merge_conversations(conv1: list[dict], conv2: list[dict]) -> list[dict]:
    """使用智慧雙重 diff 找出重疊並合併兩份對話，徹底解決重複問題"""
    if not conv1: return conv2
    if not conv2: return conv1

    c1 = [m['content'].strip() for m in conv1]
    c2 = [m['content'].strip() for m in conv2]
    
    sm = difflib.SequenceMatcher(None, c1, c2)
    match = sm.find_longest_match(0, len(c1), 0, len(c2))
    
    if match.size > 0:
        matched_text_len = sum(len(c1[i]) for i in range(match.a, match.a + match.size))
        if matched_text_len > 20:
            if match.a < match.b:
                older, newer = conv2, conv1
                match_older_start, match_newer_start = match.b, match.a
            else:
                older, newer = conv1, conv2
                match_older_start, match_newer_start = match.a, match.b
                
            merged = older[:match_older_start + match.size] + newer[match_newer_start + match.size:]
            return merged

    def find_and_merge_str(older_conv, newer_conv):
        for i in range(max(0, len(older_conv)-3), len(older_conv)):
            for j in range(0, min(3, len(newer_conv))):
                s1 = older_conv[i]['content']
                s2 = newer_conv[j]['content']
                
                s1_tail = s1[-2000:] if len(s1) > 2000 else s1
                s2_head = s2[:2000] if len(s2) > 2000 else s2
                
                sm_str = difflib.SequenceMatcher(None, s1_tail, s2_head)
                m_str = sm_str.find_longest_match(0, len(s1_tail), 0, len(s2_head))
                
                if m_str.size > 30:
                    actual_a = len(s1) - len(s1_tail) + m_str.a
                    actual_b = m_str.b
                    merged_content = s1[:actual_a] + s2[actual_b:]
                    merged_msg = {
                        'role': older_conv[i]['role'], 
                        'content': merged_content, 
                        'original_header': older_conv[i].get('original_header', '**Assistant:**')
                    }
                    if 'duration' in older_conv[i]:
                        merged_msg['duration'] = older_conv[i]['duration']
                    elif 'duration' in newer_conv[j]:
                        merged_msg['duration'] = newer_conv[j]['duration']
                        
                    return older_conv[:i] + [merged_msg] + newer_conv[j+1:]
        return None

    res = find_and_merge_str(conv1, conv2)
    if res: return res
    res = find_and_merge_str(conv2, conv1)
    if res: return res

    return conv1 + conv2


# ── HTML 模板產生器 ──────────────────────────────────────────

def generate_html(filename: str, messages_html: str) -> str:
    html_template = (
        '<!DOCTYPE html>\n'
        '<html lang="zh-TW">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{filename} - LLM Log Reader</title>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">\n'
        '<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>\n'
        '<style>\n'
        '  :root {\n'
        '    --bg:          #f5f6fa;\n'
        '    --surface:     #ffffff;\n'
        '    --surface2:    #f0f2f7;\n'
        '    --border:      #d8dce8;\n'
        '    --accent:      #2563eb;\n'
        '    --accent2:     #1d4ed8;\n'
        '    --user-bg:     #eff6ff;\n'
        '    --user-border: #93c5fd;\n'
        '    --ai-bg:       #ffffff;\n'
        '    --text:        #0f172a;\n'
        '    --text-dim:    #374151;\n'
        '    --text-bright: #030712;\n'
        '    --tag-user:    #2563eb;\n'
        '    --tag-ai:      #7c3aed;\n'
        '    --radius:      12px;\n'
        "    --mono:        'JetBrains Mono', monospace;\n"
        "    --sans:        'Noto Sans TC', sans-serif;\n"
        '  }\n'
        '  * { box-sizing: border-box; margin: 0; padding: 0; }\n'
        '  body { background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 15px; line-height: 1.7; min-height: 100vh; }\n'
        '  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 24px; position: fixed; top: 0; left: 0; width: 100%; z-index: 1000; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }\n'
        '  .logo { font-family: var(--mono); font-size: 12px; color: var(--accent); letter-spacing: 0.12em; text-transform: uppercase; flex-shrink: 0; }\n'
        '  .file-name-display { flex: 1; font-family: var(--mono); font-size: 14px; color: var(--text-bright); background: var(--surface2); padding: 6px 12px; border-radius: 7px; border: 1px solid var(--border); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n'
        '  .stats { font-size: 12px; color: var(--text-dim); font-family: var(--mono); white-space: nowrap; flex-shrink: 0; }\n'
        '  .btn { background: var(--surface2); border: 1px solid var(--border); color: var(--text-dim); padding: 5px 11px; border-radius: 6px; cursor: pointer; font-size: 12px; font-family: var(--mono); transition: all 0.2s; white-space: nowrap; flex-shrink: 0; }\n'
        '  .btn:hover { border-color: var(--accent); color: var(--accent); background: #eff6ff; }\n'
        '  main { max-width: 860px; margin: 0 auto; padding: 80px 24px 80px; }\n'
        '  .message { margin-bottom: 14px; border-radius: var(--radius); overflow: hidden; border: 1px solid var(--border); background: var(--surface); transition: border-color 0.2s, box-shadow 0.2s; scroll-margin-top: 85px; }\n'
        '  .message:hover { border-color: #93c5fd; box-shadow: 0 2px 8px rgba(37,99,235,0.07); }\n'
        '  .message.user { border-color: var(--user-border); background: var(--user-bg); }\n'
        '  .message.user .msg-header { background: rgba(37,99,235,0.06); border-bottom: 1px solid var(--user-border); }\n'
        '  .message.user .role-tag { color: var(--tag-user); border-color: var(--tag-user); background: rgba(37,99,235,0.08); }\n'
        '  .message.ai { background: var(--ai-bg); }\n'
        '  .message.ai .msg-header { background: rgba(124,58,237,0.04); border-bottom: 1px solid var(--border); cursor: pointer; user-select: none; }\n'
        '  .message.ai .msg-header:hover { background: rgba(124,58,237,0.09); }\n'
        '  .message.ai .role-tag { color: var(--tag-ai); border-color: var(--tag-ai); background: rgba(124,58,237,0.07); }\n'
        '  .msg-header { display: flex; align-items: center; gap: 10px; padding: 9px 16px; }\n'
        '  .role-tag { font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.08em; text-transform: uppercase; border: 1px solid; padding: 2px 8px; border-radius: 4px; flex-shrink: 0; }\n'
        '  .msg-preview { font-size: 13px; color: #374151; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }\n'
        '  .toggle-icon { color: #374151; font-size: 13px; flex-shrink: 0; transition: transform 0.22s ease; }\n'
        '  .message.ai.open .toggle-icon { transform: rotate(90deg); }\n'
        '  .msg-index { font-family: var(--mono); font-size: 11px; color: #374151; opacity: 0.8; flex-shrink: 0; }\n'
        '  .q-index { font-family: var(--mono); font-size: 11px; font-weight: 500; color: var(--accent); background: rgba(37,99,235,0.1); border: 1px solid rgba(37,99,235,0.25); padding: 1px 7px; border-radius: 4px; flex-shrink: 0; }\n'
        '  .jump-selector-wrap { position: relative; flex-shrink: 0; }\n'
        "  .jump-selector-wrap::after { content: '▾'; position: absolute; right: 8px; top: 50%; transform: translateY(-50%); color: var(--text-dim); pointer-events: none; font-size: 11px; }\n"
        '  #jump-select { background: var(--surface2); border: 1px solid var(--border); color: var(--text-bright); padding: 6px 24px 6px 10px; border-radius: 7px; font-family: var(--mono); font-size: 12px; cursor: pointer; appearance: none; -webkit-appearance: none; transition: border-color 0.2s; max-width: 200px; }\n'
        '  #jump-select:hover, #jump-select:focus { border-color: var(--accent); outline: none; }\n'
        '  .action-btn { background: transparent; border: 1px solid var(--border); color: var(--text-dim); padding: 2px 9px; border-radius: 5px; cursor: pointer; font-size: 11px; font-family: var(--mono); transition: all 0.18s; flex-shrink: 0; display: flex; align-items: center; gap: 4px; white-space: nowrap; }\n'
        '  .message.user .action-btn { border-color: var(--user-border); color: var(--accent); }\n'
        '  .message.user .copy-btn:hover { background: rgba(37,99,235,0.1); border-color: var(--accent); }\n'
        '  .message.user .edit-btn:hover { background: rgba(217,119,6,0.1); border-color: #d97706; color: #d97706; }\n'
        '  .message.user .delete-btn:hover { background: rgba(220,38,38,0.1); border-color: #dc2626; color: #dc2626; }\n'
        '  .message.ai .action-btn { border-color: #d8b4fe; color: #7c3aed; }\n'
        '  .message.ai .copy-btn:hover { background: rgba(124,58,237,0.1); border-color: #7c3aed; }\n'
        '  .message.ai .delete-btn:hover { background: rgba(220,38,38,0.1); border-color: #dc2626; color: #dc2626; }\n'
        '  .copy-btn.copied { color: #16a34a !important; border-color: #86efac !important; background: rgba(22,163,74,0.07) !important; }\n'
        '  .translate-btn { border-color: #a5b4fc !important; color: #4f46e5 !important; }\n'
        '  .translate-btn:hover { background: rgba(79,70,229,0.08) !important; border-color: #4f46e5 !important; }\n'
        '  .translate-btn.translating { opacity: 0.6; cursor: wait; }\n'
        '  .translation-box { display: none; margin: 0 18px 14px; padding: 10px 14px; background: #f5f3ff; border: 1px solid #c4b5fd; border-radius: 8px; font-size: 14px; color: #2e1065; line-height: 1.65; word-break: break-word; }\n'
        '  .translation-box.show { display: block; }\n'
        '  .translation-box .tl-label { font-family: var(--mono); font-size: 10px; color: #7c3aed; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 8px; display: block; border-bottom: 1px solid rgba(124,58,237,0.2); padding-bottom: 4px; }\n'
        '  .tl-content.plain-text { white-space: pre-wrap; }\n'
        '  .tl-content p { margin-bottom: 10px; }\n'
        '  .tl-content p:last-child { margin-bottom: 0; }\n'
        '  .tl-content pre { background: rgba(255,255,255,0.7); border: 1px solid #c4b5fd; border-radius: 6px; padding: 12px; overflow-x: auto; margin: 10px 0; }\n'
        '  .tl-content code { font-family: var(--mono); font-size: 13px; background: rgba(255,255,255,0.5); padding: 2px 4px; border-radius: 4px; }\n'
        '  .tl-content pre code { background: transparent; padding: 0; border: none; }\n'
        '  .tl-content ul, .tl-content ol { padding-left: 20px; margin-bottom: 10px; }\n'
        '  .tl-content blockquote { border-left: 3px solid #8b5cf6; padding-left: 10px; color: #5b21b6; margin: 10px 0; }\n'
        '  .msg-body { padding: 18px 22px; }\n'
        '  .message.ai .msg-body { display: none; }\n'
        '  .message.ai.open .msg-body { display: block; }\n'
        '  .user-text { font-size: 15px; color: var(--text-bright); white-space: pre-wrap; word-break: break-word; font-family: var(--sans); line-height: 1.7; }\n'
        '  .edit-textarea { width: 100%; min-height: 100px; padding: 12px; border: 1px solid var(--accent); border-radius: 8px; font-family: var(--sans); font-size: 15px; line-height: 1.7; resize: vertical; outline: none; background: #fff; }\n'
        '  .msg-body p { margin-bottom: 12px; }\n'
        '  .msg-body p:last-child { margin-bottom: 0; }\n'
        '  .msg-body h1,.msg-body h2,.msg-body h3, .msg-body h4,.msg-body h5,.msg-body h6 { color: var(--text-bright); margin: 20px 0 10px; line-height: 1.4; }\n'
        '  .msg-body h1 { font-size: 1.4em; } .msg-body h2 { font-size: 1.2em; border-bottom: 1px solid var(--border); padding-bottom: 6px; } .msg-body h3 { font-size: 1.05em; color: var(--accent2); }\n'
        '  .msg-body ul,.msg-body ol { padding-left: 24px; margin-bottom: 12px; }\n'
        '  .msg-body li { margin-bottom: 4px; }\n'
        '  .msg-body code { background: #f1f5f9; border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; font-family: var(--mono); font-size: 13px; color: #be123c; }\n'
        '  .msg-body pre { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 16px; overflow-x: auto; margin: 12px 0; position: relative; }\n'
        '  .msg-body pre code { background: none; border: none; padding: 0; color: var(--text); font-size: 13px; line-height: 1.6; }\n'
        '  .lang-label { position: absolute; top: 8px; right: 12px; font-family: var(--mono); font-size: 11px; color: var(--text-dim); text-transform: uppercase; }\n'
        '  .msg-body blockquote { border-left: 3px solid var(--accent); padding: 8px 16px; margin: 12px 0; background: rgba(37,99,235,0.04); border-radius: 0 6px 6px 0; color: var(--text-dim); }\n'
        '  .msg-body table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }\n'
        '  .msg-body th,.msg-body td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }\n'
        '  .msg-body th { background: var(--surface2); color: var(--text-bright); font-weight: 500; }\n'
        '  .msg-body tr:nth-child(even) td { background: #f8fafc; }\n'
        '  .msg-body strong { color: var(--text-bright); font-weight: 500; }\n'
        '  .msg-body em { color: var(--accent2); }\n'
        '  .msg-body a { color: var(--accent); text-decoration: none; }\n'
        '  .msg-body a:hover { text-decoration: underline; }\n'
        '  .msg-body hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }\n'
        '  ::-webkit-scrollbar { width: 6px; height: 6px; }\n'
        '  ::-webkit-scrollbar-track { background: var(--bg); }\n'
        '  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }\n'
        '  ::-webkit-scrollbar-thumb:hover { background: #93c5fd; }\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<header>\n'
        '  <span class="logo">LLM Log Reader</span>\n'
        f'  <div class="file-name-display">{filename}</div>\n'
        '  <span class="stats" id="stats"></span>\n'
        '  <div class="jump-selector-wrap">\n'
        '    <select id="jump-select" onchange="jumpToQuestion(this.value)">\n'
        '      <option value="">— Jump to question —</option>\n'
        '    </select>\n'
        '  </div>\n'
        '  <button class="btn" onclick="collapseAll()">Collapse all</button>\n'
        '  <button class="btn" onclick="expandAll()">Expand all</button>\n'
        '</header>\n'
        '<main>\n'
        f'  <div id="messages">{messages_html}</div>\n'
        '</main>\n'
        '<script>\n'
        '  const CHECK_ICON = \'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0"><polyline points="2,8 6,12 14,4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>\';\n'
        '  const TRANSLATE_ICON = \'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0"><path d="M1 3h8M5 1v2M3 3c.3 2 1.5 3.8 3 5M7 7c-1 1-2.5 1.8-4 2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 9l2-5 2 5M10 12h2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>\';\n'
        '  const SPIN_ICON = \'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0;animation:spin .7s linear infinite"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="1.5" stroke-dasharray="20 18"/></svg>\';\n'
        '  const EDIT_ICON = \'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0"><path d="M12 2l2 2-9 9H3v-2l9-9z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\';\n'
        '  const DELETE_ICON = \'<svg width="12" height="12" viewBox="0 0 16 16" fill="none" style="flex-shrink:0"><path d="M2 4h12M5 4V2h6v2M3 4v10a2 2 0 002 2h6a2 2 0 002-2V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>\';\n'
        '  function updateStats() {\n'
        '    const u = document.querySelectorAll("#messages .message.user").length;\n'
        '    const a = document.querySelectorAll("#messages .message.ai").length;\n'
        '    document.getElementById("stats").textContent = (u + a > 0) ? u + " Q / " + a + " A" : "";\n'
        '  }\n'
        '  function rebuildJumpMenu() {\n'
        '    const sel = document.getElementById("jump-select");\n'
        '    sel.innerHTML = \'<option value="">— Jump to question —</option>\';\n'
        '    let qNum = 0;\n'
        '    document.querySelectorAll("#messages .message.user").forEach(el => {\n'
        '      qNum++;\n'
        '      const preview = el.querySelector(".user-text") ? el.querySelector(".user-text").textContent.trim().slice(0, 30) : "";\n'
        '      const label = "Q" + qNum + (preview ? "  " + preview + (preview.length >= 30 ? "…" : "") : "");\n'
        '      el.dataset.qnum = qNum;\n'
        '      const qIndexSpan = el.querySelector(".q-index");\n'
        '      if(qIndexSpan) qIndexSpan.textContent = "Q" + qNum;\n'
        '      const opt = document.createElement("option");\n'
        '      opt.value = qNum;\n'
        '      opt.textContent = label;\n'
        '      sel.appendChild(opt);\n'
        '    });\n'
        '  }\n'
        '  function jumpToQuestion(qnum) {\n'
        '    if (!qnum) return;\n'
        '    const el = document.querySelector(\'[data-qnum="\' + qnum + \'"]\');\n'
        '    if (el) {\n'
        '      const headerHeight = 85;\n'
        '      const rect = el.getBoundingClientRect();\n'
        '      const scrollTop = window.pageYOffset || document.documentElement.scrollTop;\n'
        '      window.scrollTo({ top: rect.top + scrollTop - headerHeight, behavior: "smooth" });\n'
        '      document.getElementById("jump-select").value = "";\n'
        '    }\n'
        '  }\n'
        '  function bindToggles() {\n'
        '    document.querySelectorAll("#messages .message.ai .msg-header").forEach(h => {\n'
        '      h.onclick = (e) => {\n'
        '        if (e.target.closest("button")) return;\n'
        '        h.closest(".message").classList.toggle("open");\n'
        '      };\n'
        '    });\n'
        '  }\n'
        '  function bindCopyButtons() {\n'
        '    document.querySelectorAll(".copy-btn").forEach(btn => {\n'
        '      btn.onclick = function(e) {\n'
        '        e.stopPropagation();\n'
        '        const text = this.dataset.text;\n'
        '        const doMark = () => {\n'
        '          const orig = this.innerHTML;\n'
        '          this.innerHTML = CHECK_ICON + " Copied!";\n'
        '          this.classList.add("copied");\n'
        '          setTimeout(() => { this.innerHTML = orig; this.classList.remove("copied"); }, 1800);\n'
        '        };\n'
        '        if (navigator.clipboard && navigator.clipboard.writeText) {\n'
        '          navigator.clipboard.writeText(text).then(doMark).catch(() => { legacyCopy(text); doMark(); });\n'
        '        } else { legacyCopy(text); doMark(); }\n'
        '      };\n'
        '    });\n'
        '  }\n'
        '  function legacyCopy(text) {\n'
        '    const ta = document.createElement("textarea");\n'
        '    ta.value = text;\n'
        '    ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";\n'
        '    document.body.appendChild(ta);\n'
        '    ta.select();\n'
        '    document.execCommand("copy");\n'
        '    document.body.removeChild(ta);\n'
        '  }\n'
        '  function bindTranslateButtons() {\n'
        '    document.querySelectorAll(".translate-btn").forEach(btn => {\n'
        '      btn.onclick = async function(e) {\n'
        '        e.stopPropagation();\n'
        '        const card = this.closest(".message");\n'
        '        const box  = card.querySelector(".translation-box");\n'
        '        const content = card.querySelector(".tl-content");\n'
        '        if (box.classList.contains("show")) {\n'
        '          box.classList.remove("show");\n'
        '          this.innerHTML = TRANSLATE_ICON + " Translate";\n'
        '          return;\n'
        '        }\n'
        '        if (content.dataset.translated) {\n'
        '          box.classList.add("show");\n'
        '          this.innerHTML = TRANSLATE_ICON + " Hide";\n'
        '          return;\n'
        '        }\n'
        '        this.classList.add("translating");\n'
        '        this.innerHTML = SPIN_ICON + " Translating…";\n'
        '        try {\n'
        '          const text = this.dataset.text;\n'
        '          const url  = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=en&dt=t";\n'
        '          const res = await fetch(url, {\n'
        '            method: "POST",\n'
        '            headers: { "Content-Type": "application/x-www-form-urlencoded" },\n'
        '            body: "q=" + encodeURIComponent(text)\n'
        '          });\n'
        '          const data = await res.json();\n'
        '          const translated = data[0].map(s => s[0]).join("");\n'
        '          if (card.classList.contains("ai")) {\n'
        '            content.innerHTML = marked.parse(translated);\n'
        '            content.classList.remove("plain-text");\n'
        '          } else {\n'
        '            content.textContent = translated;\n'
        '            content.classList.add("plain-text");\n'
        '          }\n'
        '          content.dataset.translated = "1";\n'
        '          box.classList.add("show");\n'
        '          this.innerHTML = TRANSLATE_ICON + " Hide";\n'
        '        } catch(err) {\n'
        '          content.textContent = "Translation failed: " + err.message;\n'
        '          content.classList.add("plain-text");\n'
        '          box.classList.add("show");\n'
        '          this.innerHTML = TRANSLATE_ICON + " Translate";\n'
        '        }\n'
        '        this.classList.remove("translating");\n'
        '      };\n'
        '    });\n'
        '  }\n'
        '  function bindEditButtons() {\n'
        '    document.querySelectorAll(".edit-btn").forEach(btn => {\n'
        '      btn.onclick = function(e) {\n'
        '        e.stopPropagation();\n'
        '        const card = this.closest(".message.user");\n'
        '        const textDiv = card.querySelector(".user-text");\n'
        '        const isEditing = card.classList.contains("editing");\n'
        '        if (isEditing) {\n'
        '          const textarea = card.querySelector(".edit-textarea");\n'
        '          const newText = textarea.value;\n'
        '          textDiv.textContent = newText;\n'
        '          textDiv.style.display = "";\n'
        '          textarea.remove();\n'
        '          card.classList.remove("editing");\n'
        '          this.innerHTML = EDIT_ICON + " Edit";\n'
        '          card.querySelector(".copy-btn").dataset.text = newText;\n'
        '          card.querySelector(".translate-btn").dataset.text = newText;\n'
        '          const tlContent = card.querySelector(".tl-content");\n'
        '          tlContent.dataset.translated = "";\n'
        '          tlContent.textContent = "";\n'
        '          card.querySelector(".translation-box").classList.remove("show");\n'
        '          card.querySelector(".translate-btn").innerHTML = TRANSLATE_ICON + " Translate";\n'
        '          rebuildJumpMenu();\n'
        '        } else {\n'
        '          const currentText = textDiv.textContent;\n'
        '          const textarea = document.createElement("textarea");\n'
        '          textarea.className = "edit-textarea";\n'
        '          textarea.value = currentText;\n'
        '          textDiv.style.display = "none";\n'
        '          textDiv.parentNode.insertBefore(textarea, textDiv);\n'
        '          card.classList.add("editing");\n'
        '          this.innerHTML = CHECK_ICON + " Save";\n'
        '        }\n'
        '      };\n'
        '    });\n'
        '  }\n'
        '  function bindDeleteButtons() {\n'
        '    document.querySelectorAll(".delete-btn").forEach(btn => {\n'
        '      btn.onclick = function(e) {\n'
        '        e.stopPropagation();\n'
        '        if(confirm("Are you sure you want to delete this message?")) {\n'
        '          this.closest(".message").remove();\n'
        '          updateStats();\n'
        '          rebuildJumpMenu();\n'
        '        }\n'
        '      };\n'
        '    });\n'
        '  }\n'
        '  function collapseAll() { document.querySelectorAll("#messages .message.ai").forEach(m => m.classList.remove("open")); }\n'
        '  function expandAll() { document.querySelectorAll("#messages .message.ai").forEach(m => m.classList.add("open")); }\n'
        '  updateStats();\n'
        '  bindToggles();\n'
        '  bindCopyButtons();\n'
        '  bindTranslateButtons();\n'
        '  bindEditButtons();\n'
        '  bindDeleteButtons();\n'
        '  rebuildJumpMenu();\n'
        '</script>\n'
        '</body>\n'
        '</html>'
    )
    return html_template


# ── 核心解析邏輯 ─────────────────────────────────────────────────────────────

def simple_markdown_to_html(md: str) -> str:
    lines = md.split('\n')
    result = []
    in_code_block, in_table, in_list = False, False, False
    code_lang, code_lines = '', []
    table_rows, list_items, list_type = [], [], None

    def flush_list():
        nonlocal in_list, list_type, list_items
        if not list_items: return ''
        out = f'<{list_type}>\n' + ''.join(f'<li>{inline_md(x)}</li>\n' for x in list_items) + f'</{list_type}>\n'
        list_items.clear(); in_list = False; list_type = None
        return out

    def flush_table():
        nonlocal in_table, table_rows
        if not table_rows: return ''
        out = '<table>\n'
        for i, row in enumerate(table_rows):
            if i == 1 and all(re.match(r'^[-:]+$', c.strip()) for c in row): continue
            tag = 'th' if i == 0 else 'td'
            out += '<tr>' + ''.join(f'<{tag}>{inline_md(c.strip())}</{tag}>' for c in row) + '</tr>\n'
        out += '</table>\n'
        table_rows.clear(); in_table = False
        return out

    def inline_md(t):
        t = html_lib.escape(t, quote=False)
        t = re.sub(r'`([^`]+)`', lambda m: f'<code>{m.group(1)}</code>', t)
        t = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', t)
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'__(.+?)__', r'<strong>\1</strong>', t)
        t = re.sub(r'\*([^*\n]+)\*', r'<em>\1</em>', t)
        t = re.sub(r'_([^_\n]+)_', r'<em>\1</em>', t)
        t = re.sub(r'~~(.+?)~~', r'<del>\1</del>', t)
        t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', t)
        return t

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            if in_code_block:
                lang_html = f'<span class="lang-label">{html_lib.escape(code_lang)}</span>' if code_lang else ''
                result.append(f'<pre>{lang_html}<code>{html_lib.escape(chr(10).join(code_lines))}</code></pre>')
                in_code_block, code_lang, code_lines = False, '', []
            else:
                if in_list: result.append(flush_list())
                if in_table: result.append(flush_table())
                in_code_block, code_lang = True, line[3:].strip()
            i += 1; continue
        if in_code_block:
            code_lines.append(line); i += 1; continue
        if '|' in line and line.strip().startswith('|'):
            if in_list: result.append(flush_list())
            in_table = True
            table_rows.append([c for c in line.strip().strip('|').split('|')])
            i += 1; continue
        elif in_table: result.append(flush_table())
        if not line.strip():
            if in_list: result.append(flush_list())
            if in_table: result.append(flush_table())
            result.append(''); i += 1; continue
        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if m:
            if in_list: result.append(flush_list())
            lv = len(m.group(1))
            result.append(f'<h{lv}>{inline_md(m.group(2))}</h{lv}>')
            i += 1; continue
        if re.match(r'^[-*_]{3,}\s*$', line):
            if in_list: result.append(flush_list())
            result.append('<hr>'); i += 1; continue
        if line.startswith('> '):
            if in_list: result.append(flush_list())
            result.append(f'<blockquote>{inline_md(line[2:])}</blockquote>')
            i += 1; continue
        m = re.match(r'^[-*+]\s+(.*)', line)
        if m:
            in_list, list_type = True, 'ul'
            list_items.append(m.group(1)); i += 1; continue
        m = re.match(r'^\d+\.\s+(.*)', line)
        if m:
            in_list, list_type = True, 'ol'
            list_items.append(m.group(1)); i += 1; continue
        if in_list: result.append(flush_list())
        result.append(f'<p>{inline_md(line)}</p>')
        i += 1
    if in_code_block:
        result.append(f'<pre><code>{html_lib.escape(chr(10).join(code_lines))}</code></pre>')
    if in_list: result.append(flush_list())
    if in_table: result.append(flush_table())
    return '\n'.join(result)


def parse_conversation(md_content: str) -> list[dict]:
    blocks = []
    
    header_pattern = r'^(#{1,4}\s*(?:Human|User|Assistant|AI|Claude|You|Gemini)[^\n]*)'
    bold_pattern = r'^(\*\*(?:Human|User|Assistant|AI|Claude|You|Gemini):\*\*)'
    
    if re.search(header_pattern, md_content, re.MULTILINE | re.IGNORECASE):
        parts = re.split(header_pattern, md_content, flags=re.MULTILINE | re.IGNORECASE)
    elif re.search(bold_pattern, md_content, re.MULTILINE | re.IGNORECASE):
        parts = re.split(bold_pattern, md_content, flags=re.MULTILINE | re.IGNORECASE)
    else:
        md_content = re.sub(r'\n*---\s*$', '', md_content).strip()
        if md_content:
            blocks.append({'role': 'ai', 'content': md_content, 'original_header': '**Assistant:**'})
        return blocks

    for i in range(1, len(parts) - 1, 2):
        header = parts[i]
        content = parts[i+1]
        
        rm = re.search(r'(Human|User|Assistant|AI|Claude|You|Gemini)', header, re.IGNORECASE)
        if rm:
            role_str = rm.group(1).lower()
            role = 'user' if role_str in ('human', 'user', 'you') else 'ai'
            content = re.sub(r'\n*---\s*$', '', content).strip()
            
            duration = None
            if role == 'ai':
                sec_match = re.search(r'([\d\.]+)\s*s\b', header)
                if sec_match:
                    try:
                        duration = float(sec_match.group(1))
                    except ValueError:
                        pass
            
            if content:
                msg_dict = {'role': role, 'content': content, 'original_header': header.strip()}
                if duration is not None:
                    msg_dict['duration'] = duration
                blocks.append(msg_dict)
                
    return blocks

def generate_markdown_export(header: str, messages: list[dict]) -> str:
    out = ""
    if header:
        out += header + "\n\n---\n\n"
        
    for m in messages:
        default_label = "**User:**" if m['role'] == 'user' else "**Assistant:**"
        role_label = m.get('original_header', default_label)
        
        out += role_label + "\n\n"
        out += m['content'] + "\n\n---\n\n"
        
    return out.strip() + "\n"


def generate_user_prompts_export(messages: list[dict]) -> str:
    out = ""
    q_count = 1
    for m in messages:
        if m['role'] == 'user':
            out += f"### Q{q_count}\n\n"
            out += m['content'] + "\n\n---\n\n"
            q_count += 1
            
    return out.strip() + "\n"

# ── 更新：修改圖表配色方案，提升專業感與清晰度 ──────────────────────────────
def render_duration_chart(messages: list[dict]):
    """產生統計圖表：總時間(折線)、平均時間(折線)、回答次數(長條)"""
    chart_data = []
    q_count = 0
    cumulative_duration = 0.0
    
    current_q_prompt = "No prompt"
    current_q_ai_count = 0
    current_q_duration = 0.0
    
    for msg in messages:
        if msg['role'] == 'user':
            if q_count > 0:
                cumulative_duration += current_q_duration
                avg_dur = current_q_duration / current_q_ai_count if current_q_ai_count > 0 else 0.0
                chart_data.append({
                    "Question_Turn": q_count, 
                    "Cumulative_Duration": round(cumulative_duration, 2), 
                    "AI_Answer_Count": current_q_ai_count, 
                    "Total_Duration": round(current_q_duration, 2),
                    "Average_Duration": round(avg_dur, 2),
                    "Prompt": current_q_prompt
                })
                
            q_count += 1
            current_q_prompt = msg['content'].strip()[:40].replace('\n', ' ')
            if len(msg['content'].strip()) > 40:
                current_q_prompt += "..."
                
            current_q_ai_count = 0
            current_q_duration = 0.0
            
        elif msg['role'] == 'ai':
            d = msg.get('duration')
            if d is not None:
                current_q_ai_count += 1
                current_q_duration += d
                
    if q_count > 0:
        cumulative_duration += current_q_duration
        avg_dur = current_q_duration / current_q_ai_count if current_q_ai_count > 0 else 0.0
        chart_data.append({
            "Question_Turn": q_count,
            "Cumulative_Duration": round(cumulative_duration, 2),
            "AI_Answer_Count": current_q_ai_count,
            "Total_Duration": round(current_q_duration, 2),
            "Average_Duration": round(avg_dur, 2),
            "Prompt": current_q_prompt
        })
                
    if not chart_data or all(d["AI_Answer_Count"] == 0 for d in chart_data):
        return None
        
    df = pd.DataFrame(chart_data)
    
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # 1. 每次問題的回答次數 (長條圖) -> 採用更內斂的淺灰色系，作為背景輔助資訊
    fig.add_trace(
        go.Bar(
            x=df["Question_Turn"],
            y=df["AI_Answer_Count"],
            name="回答次數 (Count)",
            marker_color="rgba(148, 163, 184, 0.25)", # 淺石板灰 (Slate)
            marker_line=dict(color="rgba(148, 163, 184, 0.6)", width=1),
            hovertemplate="回答次數: <b>%{y} 次</b><extra></extra>"
        ),
        secondary_y=True,
    )
    
    # 2. 每次問題的總回答時間 (折線圖) -> 採用亮藍色，作為主要焦點
    fig.add_trace(
        go.Scatter(
            x=df["Question_Turn"],
            y=df["Total_Duration"],
            mode="lines+markers",
            name="總耗時 (Total Time)",
            line=dict(color="#3b82f6", width=3), # Blue 500
            marker=dict(size=8, color="#3b82f6", symbol="circle"),
            customdata=df[["Prompt", "Cumulative_Duration"]],
            hovertemplate=(
                "總耗時: <b>%{y}s</b><br>"
                "累計總耗時: %{customdata[1]}s<br>"
                "發問預覽: %{customdata[0]}<extra></extra>"
            )
        ),
        secondary_y=False,
    )
    
    # 3. 每次問題的平均回答時間 (折線圖) -> 採用對比的翡翠綠虛線
    fig.add_trace(
        go.Scatter(
            x=df["Question_Turn"],
            y=df["Average_Duration"],
            mode="lines+markers",
            name="平均耗時 (Avg Time)",
            line=dict(color="#10b981", width=3, dash='dot'), # Emerald 500
            marker=dict(size=8, color="#10b981", symbol="diamond"),
            hovertemplate="平均耗時: <b>%{y}s</b><extra></extra>"
        ),
        secondary_y=False,
    )
    
    fig.update_layout(
        title="⏱️ AI Response Analytics",
        xaxis_title="Question Turn (第幾次問題)",
        xaxis=dict(tickmode='linear', tick0=1, dtick=1),
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            orientation="h", 
            yanchor="bottom", 
            y=1.02, 
            xanchor="right", 
            x=1
        ),
        margin=dict(l=40, r=40, t=80, b=40),
        height=550
    )
    
    fig.update_yaxes(title_text="耗時 (Seconds)", secondary_y=False)
    fig.update_yaxes(title_text="次數 (Count)", secondary_y=True, showgrid=False)
    
    return fig

def render_messages_html(messages: list[dict]) -> str:
    if not messages:
        return '<div class="empty-state"><h2>No messages found</h2></div>'
        
    COPY_SVG = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><rect x="5" y="5" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/><path d="M3 11H2.5A1.5 1.5 0 0 1 1 9.5v-7A1.5 1.5 0 0 1 2.5 1h7A1.5 1.5 0 0 1 11 2.5V3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
    TRANS_SVG = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M1 3h8M5 1v2M3 3c.3 2 1.5 3.8 3 5M7 7c-1 1-2.5 1.8-4 2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 9l2-5 2 5M10 12h2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    EDIT_SVG = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M12 2l2 2-9 9H3v-2l9-9z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    DEL_SVG = '<svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M5 4V2h6v2M3 4v10a2 2 0 002 2h6a2 2 0 002-2V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    
    parts = []
    q_count = 0
    
    for idx, msg in enumerate(messages, 1):
        d_text = (msg['content'].replace('&', '&amp;')
                                .replace('"', '&quot;')
                                .replace("'", '&#39;'))
        
        if msg['role'] == 'user':
            q_count += 1
            plain = html_lib.escape(msg['content'])
            user_html = (
                f'<div class="message user">\n'
                f'  <div class="msg-header">\n'
                f'    <span class="role-tag">YOU</span>\n'
                f'    <span class="msg-index">#{idx}</span>\n'
                f'    <span class="q-index">Q{q_count}</span>\n'
                f'    <div style="flex:1"></div>\n'
                f'    <button class="action-btn copy-btn" data-text="{d_text}">{COPY_SVG} Copy</button>\n'
                f'    <button class="action-btn translate-btn" data-text="{d_text}">{TRANS_SVG} Translate</button>\n'
                f'    <button class="action-btn edit-btn">{EDIT_SVG} Edit</button>\n'
                f'    <button class="action-btn delete-btn">{DEL_SVG} Delete</button>\n'
                f'  </div>\n'
                f'  <div class="msg-body"><div class="user-text">{plain}</div></div>\n'
                f'  <div class="translation-box"><span class="tl-label">EN Translation</span><span class="tl-content"></span></div>\n'
                f'</div>'
            )
            parts.append(user_html)
            
        else:
            html = simple_markdown_to_html(msg['content'])
            preview = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html)).strip()[:90]
            if len(preview) >= 90:
                preview += '…'
            
            ai_html = (
                f'<div class="message ai">\n'
                f'  <div class="msg-header">\n'
                f'    <span class="role-tag">AI</span>\n'
                f'    <span class="msg-preview">{preview}</span>\n'
                f'    <span class="msg-index">#{idx}</span>\n'
                f'    <div style="flex:1"></div>\n'
                f'    <button class="action-btn copy-btn" data-text="{d_text}">{COPY_SVG} Copy</button>\n'
                f'    <button class="action-btn translate-btn" data-text="{d_text}">{TRANS_SVG} Translate</button>\n'
                f'    <button class="action-btn delete-btn">{DEL_SVG} Delete</button>\n'
                f'    <span class="toggle-icon" style="margin-left: 8px;">▶</span>\n'
                f'  </div>\n'
                f'  <div class="msg-body">{html}</div>\n'
                f'  <div class="translation-box"><span class="tl-label">EN Translation</span><span class="tl-content"></span></div>\n'
                f'</div>'
            )
            parts.append(ai_html)
            
    return '\n'.join(parts)


# ── Streamlit 介面 ────────────────────────────────────────────────────────────

def main():
    st.set_page_config(page_title="LLM Log Reader", layout="wide")
    
    if 'uploader_key' not in st.session_state:
        st.session_state.uploader_key = str(uuid.uuid4())
    if 'parsed_result' not in st.session_state:
        st.session_state.parsed_result = None

    st.markdown("""
        <style>
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 0rem !important;
        }
        iframe {
            margin-top: 8px !important;
        }
        </style>
    """, unsafe_allow_html=True)
    
    col_v, col_c = st.columns([3, 1], gap="large")
    
    with col_c:
        st.markdown("### 💬 LLM Log Reader")
        
        st.markdown(
            "Upload conversation logs to browse via a web interface. Supports uploading **multiple** files, and the system will automatically compare and **merge truncated long conversations**.<br><br>"
            "**Supports:** `opencode log` files, and logs from `Claude` / `Gemini` / `ChatGPT` exported by AI Exporter.", 
            unsafe_allow_html=True
        )
        
        uploaded_files = st.file_uploader(
            "Upload .md files (Multiple allowed)", 
            type=["md"], 
            accept_multiple_files=True, 
            key=st.session_state.uploader_key
        )
        
        trigger_parse = False
        
        if uploaded_files:
            if len(uploaded_files) >= 2:
                st.info("💡 Multiple files detected. Click 'Parse' to merge or 'Clear' to re-select.")
                col_btn1, col_btn2 = st.columns(2)
                
                with col_btn1:
                    if st.button("🚀 Parse", use_container_width=True):
                        trigger_parse = True
                        
                with col_btn2:
                    if st.button("🗑️ Clear", use_container_width=True):
                        st.session_state.uploader_key = str(uuid.uuid4())
                        st.session_state.parsed_result = None
                        st.rerun()
            else:
                trigger_parse = True
                
        if trigger_parse:
            with st.spinner("Parsing conversations..." if len(uploaded_files) == 1 else "Parsing and merging conversations..."):
                headers = []
                parsed_convs = []
                
                for up_file in uploaded_files:
                    raw_content = up_file.read().decode("utf-8", errors="replace")
                    
                    header = extract_header(raw_content)
                    if header:
                        headers.append(header)
                        
                    clean_content = clean_header(raw_content) 
                    msgs = parse_conversation(clean_content)
                    if msgs:
                        parsed_convs.append(msgs)
                
                if not parsed_convs:
                    st.error("No valid conversation content found.")
                else:
                    oldest_header = ""
                    if headers:
                        def get_created_time(h):
                            m = re.search(r'Created:\s*(.+?)(?:\n|$)', h)
                            if m:
                                try:
                                    return datetime.strptime(m.group(1).strip(), "%m/%d/%Y, %I:%M:%S %p")
                                except ValueError:
                                    pass
                            return datetime.max
                        oldest_header = min(headers, key=get_created_time)
                    
                    all_messages = parsed_convs[0]
                    for i in range(1, len(parsed_convs)):
                        all_messages = merge_conversations(all_messages, parsed_convs[i])
                        
                    msgs_html = render_messages_html(all_messages)
                    duration_fig = render_duration_chart(all_messages)
                    
                    export_name = uploaded_files[0].name.replace('.md', '')
                    if len(uploaded_files) > 1:
                        export_name += f"_merged_{len(uploaded_files)}_files"
                        
                    final_html = generate_html(
                        filename=export_name,
                        messages_html=msgs_html
                    )
                    
                    md_export_data = generate_markdown_export(oldest_header, all_messages)
                    user_prompts_export_data = generate_user_prompts_export(all_messages)
                    
                    st.session_state.parsed_result = {
                        "html": final_html,
                        "md": md_export_data,
                        "user_prompts_md": user_prompts_export_data,
                        "export_name": export_name,
                        "duration_fig": duration_fig,
                        "count": len(uploaded_files)
                    }
            
        if st.session_state.parsed_result:
            if st.session_state.parsed_result["count"] > 1:
                st.success(f"Parsed successfully! Merged {st.session_state.parsed_result['count']} files.")
            else:
                st.success("Parsed successfully!")
                
            col_b1, col_b2 = st.columns(2)
            
            with col_b1: 
                st.download_button("📥 Export HTML", data=st.session_state.parsed_result["html"], file_name=f"{st.session_state.parsed_result['export_name']}.html", mime="text/html", use_container_width=True)
                st.download_button("📥 Export Prompts", data=st.session_state.parsed_result["user_prompts_md"], file_name=f"{st.session_state.parsed_result['export_name']}_prompts.md", mime="text/markdown", use_container_width=True)
                
            with col_b2: 
                st.download_button("📥 Export MD", data=st.session_state.parsed_result["md"], file_name=f"{st.session_state.parsed_result['export_name']}_export.md", mime="text/markdown", use_container_width=True)
                
                # ── 更新：將 JS 觸發移出按鈕區塊，只使用原生的 st.button ────────────────
                if st.session_state.parsed_result.get("duration_fig"):
                    if st.button("📊 Show Chart", use_container_width=True):
                        st.session_state.trigger_chart_js = True
                else:
                    st.button("📊 No Chart Data", disabled=True, use_container_width=True)
            
            st.caption("💡 Hint: Left-side edits are for local browsing only. MD exports retain the original imports.")
            
        st.markdown("<br><hr style='margin: 1em 0;'>", unsafe_allow_html=True)
        
        st.markdown("""
            <div style="font-size: 0.9em; line-height: 1.6; color: #555;">
                <b>👨‍💻 Author:</b> Yen-Hung, Chen<br>
                <b>🐙 GitHub:</b> https://github.com/pplongChen<br>
                <b>📁 Repository:</b> https://github.com/pplongChen/agent_tools<br>
                <b>🌐 Website:</b> https://network-affairs.github.io/
            </div>
        """, unsafe_allow_html=True)
        
    with col_v:
        if st.session_state.parsed_result:
            if st.session_state.parsed_result.get("html"):
                components.html(st.session_state.parsed_result["html"], height=650, scrolling=True)
        else: 
            st.info("👈 Please upload conversation logs on the right panel (Click 'Parse' if uploading multiple files).")

# ── 更新：在全域最底端處理 JS 的渲染，避免撐壞佈局 ───────────────────────────
if st.session_state.get('trigger_chart_js', False):
    html_content = st.session_state.parsed_result["duration_fig"].to_html(full_html=True, include_plotlyjs='cdn')
    b64_html = base64.b64encode(html_content.encode('utf-8')).decode('utf-8')
    
    js = f"""
    <script>
        const b64Data = '{b64_html}';
        const binaryStr = window.atob(b64Data);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {{
            bytes[i] = binaryStr.charCodeAt(i);
        }}
        const decodedHTML = new TextDecoder('utf-8').decode(bytes);
        
        const newWindow = window.parent.open('', '_blank');
        if (newWindow) {{
            newWindow.document.write(decodedHTML);
            newWindow.document.close();
        }} else {{
            alert("⚠️ 請允許瀏覽器開啟彈出視窗以查看圖表！\\n(Please allow popups to view the chart.)");
        }}
    </script>
    """
    components.html(js, height=0, width=0)
    # 重置狀態
    st.session_state.trigger_chart_js = False

if __name__ == '__main__':
    main()
