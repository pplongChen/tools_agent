import re
import html as html_lib
import difflib
import uuid
import base64
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.express as px

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
        '  .message.ai .delete-btn:hover { background: rgba(220,38,38,0.1); border-color: #dc2626; color: #dc26
