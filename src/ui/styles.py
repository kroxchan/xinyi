"""CUSTOM_CSS extracted from app.py (lines 571-878 of src/app.py).

Keep in sync with app.py. This file is imported as:
    from src.ui.styles import CUSTOM_CSS
"""

CUSTOM_CSS = """
footer { display: none !important; }

/* ================================================================
   Global — smooth rendering
   ================================================================ */
.gradio-container {
    max-width: 100% !important;
    padding: 0 !important;
    margin: 0 !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

/* ================================================================
   Sidebar nav — vertical sidebar from Gradio tab-nav
   ================================================================ */
#main-tabs > .tabs {
    display: flex !important;
    flex-direction: row !important;
    gap: 0 !important;
    min-height: 100vh;
}
#main-tabs > .tabs > .tab-nav {
    flex-direction: column !important;
    width: 220px !important;
    min-width: 220px !important;
    max-width: 220px !important;
    background: #f3eded;
    border-right: 1px solid #e6dcd8 !important;
    border-bottom: none !important;
    padding: 0 !important;
    margin: 0 !important;
    gap: 2px !important;
    overflow-y: auto;
    position: sticky;
    top: 0;
    align-self: flex-start;
    height: 100vh;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav { background: #1e1a1b; border-right-color: #3a3234 !important; }
}

/* Brand header — name */
#main-tabs > .tabs > .tab-nav::before {
    content: "心译";
    display: block;
    padding: 22px 16px 4px;
    font-size: 1.3em;
    font-weight: 800;
    color: #b07c84;
    letter-spacing: .02em;
    flex-shrink: 0;
}
/* Brand header — tagline */
#main-tabs > .tabs > .tab-nav::after {
    content: "发出去之前，先译一下";
    display: block;
    padding: 0 16px 18px;
    font-size: .72em;
    font-weight: 400;
    color: #8c7b7f;
    letter-spacing: .01em;
    border-bottom: 1px solid #e6dcd8;
    margin-bottom: 8px;
    flex-shrink: 0;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav::before { color: #d4a0a8; }
    #main-tabs > .tabs > .tab-nav::after { color: #a8969a; border-bottom-color: #3a3234; }
}

/* Tab buttons */
#main-tabs > .tabs > .tab-nav > button {
    text-align: left !important;
    justify-content: flex-start !important;
    border: none !important;
    border-radius: 8px !important;
    margin: 1px 8px !important;
    padding: 9px 12px !important;
    font-size: .88em !important;
    font-weight: 450 !important;
    color: #6b5a5e !important;
    background: transparent !important;
    transition: background .15s, color .15s !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
#main-tabs > .tabs > .tab-nav > button:hover {
    background: rgba(176,124,132,.08) !important;
    color: #3d2c30 !important;
}
#main-tabs > .tabs > .tab-nav > button.selected {
    background: rgba(176,124,132,.12) !important;
    color: #2a1f22 !important;
    font-weight: 550 !important;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav > button { color: #a8969a !important; }
    #main-tabs > .tabs > .tab-nav > button:hover { background: rgba(255,255,255,.06) !important; color: #e6dcd8 !important; }
    #main-tabs > .tabs > .tab-nav > button.selected { background: rgba(212,160,168,.15) !important; color: #f0e8e4 !important; }
}

/* Section separators */
#main-tabs > .tabs > .tab-nav > button:nth-child(4),
#main-tabs > .tabs > .tab-nav > button:nth-child(8) {
    margin-top: 12px !important;
    position: relative;
}
#main-tabs > .tabs > .tab-nav > button:nth-child(4)::before,
#main-tabs > .tabs > .tab-nav > button:nth-child(8)::before {
    content: "";
    position: absolute;
    top: -7px;
    left: 12px;
    right: 12px;
    height: 1px;
    background: #e6dcd8;
}
@media (prefers-color-scheme: dark) {
    #main-tabs > .tabs > .tab-nav > button:nth-child(4)::before,
    #main-tabs > .tabs > .tab-nav > button:nth-child(8)::before { background: #3a3234; }
}

/* System tab (last) — push to bottom */
#main-tabs > .tabs > .tab-nav > button:last-child {
    margin-top: auto !important;
    border-top: 1px solid #e6dcd8 !important;
    border-radius: 0 !important;
    padding: 12px 16px !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    margin-bottom: 0 !important;
    opacity: .7;
}

/* Tab content area */
#main-tabs > .tabs > .tabitem {
    flex: 1 !important;
    min-width: 0;
    padding: 32px 40px !important;
    overflow-y: auto;
    max-height: 100vh;
}

/* ================================================================
   Chat sidebar (session list)
   ================================================================ */
/* 宽度由 #sidebar-col.chat-sidebar-wrap（心译对话）内联样式控制；勿在此用 !important 压窄 */
#sidebar-col {
    background: #f7f0ee;
    border-right: 1px solid #e6dcd8;
    border-radius: 0;
    padding: 4px 0 !important;
}
@media (prefers-color-scheme: dark) {
    #sidebar-col { background: #1a1617; border-right-color: #3a3234; }
}

/* 心译边栏内由 #sidebar-col.chat-sidebar-wrap 内联样式控制；左右 margin 会与 width:100% 叠加溢出 */
#new-chat-btn {
    margin: 4px 0 6px !important;
    font-size: .82em !important;
    padding: 6px 0 !important;
}

#session-radio {
    border: none !important;
    background: transparent !important;
    padding: 0 !important;
    overflow-y: auto;
    max-height: calc(100vh - 120px);
}
#session-radio .wrap {
    gap: 1px !important;
}
#session-radio label {
    display: flex !important;
    align-items: center !important;
    padding: 8px 10px !important;
    margin: 0 4px !important;
    border-radius: 6px !important;
    font-size: .8em !important;
    cursor: pointer !important;
    transition: background .12s !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    color: #6b5a5e !important;
    border: none !important;
    background: transparent !important;
    min-height: 0 !important;
    line-height: 1.3 !important;
}
#session-radio label:hover {
    background: rgba(176,124,132,.08) !important;
}
#session-radio label.selected,
#session-radio input:checked + span {
    background: rgba(176,124,132,.14) !important;
    color: #2a1f22 !important;
    font-weight: 550 !important;
}
#session-radio input[type="radio"] {
    display: none !important;
}
@media (prefers-color-scheme: dark) {
    #session-radio label { color: #a8969a !important; }
    #session-radio label:hover { background: rgba(255,255,255,.06) !important; }
    #session-radio label.selected { background: rgba(212,160,168,.15) !important; color: #f0e8e4 !important; }
}

#del-session-btn {
    margin: 4px 6px !important;
    font-size: .72em !important;
    opacity: .5;
    padding: 4px 0 !important;
}
#del-session-btn:hover { opacity: .8; }

/* ================================================================
   Chat area
   ================================================================ */
#chat-area .chatbot { border: none !important; }
#chat-area .message { max-width: 680px; margin: 0 auto; }
#main-chatbot { border: none !important; background: transparent !important; }

#chat-input textarea {
    border-radius: 12px !important;
    padding: 10px 14px !important;
    border: 1px solid #e6dcd8 !important;
    transition: border-color .2s, box-shadow .2s !important;
}
#chat-input textarea:focus {
    border-color: #b07c84 !important;
    box-shadow: 0 0 0 3px rgba(176,124,132,.15) !important;
    outline: none !important;
}
#send-btn {
    border-radius: 50% !important;
    width: 42px !important;
    height: 42px !important;
    min-width: 42px !important;
    padding: 0 !important;
    font-size: 1.1em !important;
}

/* ================================================================
   Analytics cards
   ================================================================ */
.stat-card {
    background: var(--block-background-fill);
    border: 1px solid var(--block-border-color);
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    min-height: 100px;
    transition: box-shadow .2s, transform .2s;
}
.stat-card:hover { box-shadow: 0 4px 16px rgba(61,44,48,.06); transform: translateY(-1px); }
.stat-card .stat-value { font-size: 2em; font-weight: 700; color: var(--body-text-color); margin: 4px 0; }
.stat-card .stat-label { font-size: .9em; color: var(--body-text-color-subdued); }

.step-card {
    padding: 12px 16px;
    margin: 6px 0;
    border-radius: 8px;
    border-left: 4px solid var(--block-border-color);
    background: var(--block-background-fill);
}
.step-ok { border-left-color: #65a88a; }
.step-fail { border-left-color: #ef4444; }

/* ================================================================
   Word cloud
   ================================================================ */
.wordcloud { display:flex; flex-wrap:wrap; gap:6px; justify-content:center; padding:16px; }
.wordcloud span {
    display:inline-block;
    padding: 4px 10px;
    border-radius: 6px;
    background: var(--block-background-fill);
    border: 1px solid var(--block-border-color);
    white-space: nowrap;
    transition: transform .15s;
}
.wordcloud span:hover { transform: scale(1.05); }

/* ================================================================
   Responsive — collapse sidebar on small screens
   ================================================================ */
@media (max-width: 768px) {
    #main-tabs > .tabs { flex-direction: column !important; }
    #main-tabs > .tabs > .tab-nav {
        width: 100% !important; min-width: 100% !important; max-width: 100% !important;
        flex-direction: row !important; height: auto !important; position: static;
        overflow-x: auto; border-right: none !important; border-bottom: 1px solid #e6dcd8 !important;
        padding: 8px !important;
    }
    #main-tabs > .tabs > .tab-nav::before { display: none; }
    #main-tabs > .tabs > .tab-nav::after { display: none; }
    #main-tabs > .tabs > .tab-nav > button { margin: 0 2px !important; white-space: nowrap; }
    #main-tabs > .tabs > .tab-nav > button:last-child { margin-top: 0 !important; }
    #main-tabs > .tabs > .tabitem { padding: 16px !important; max-height: none; }
}

/* ================================================================
   Keyboard shortcuts overlay
   ================================================================ */
.keyboard-hint {
    position: fixed;
    bottom: 20px;
    right: 20px;
    background: rgba(30, 26, 27, 0.92);
    color: #d4c4c8;
    border: 1px solid #3a3234;
    border-radius: 10px;
    padding: 12px 16px;
    font-size: .78em;
    line-height: 1.8;
    z-index: 9999;
    max-width: 220px;
    backdrop-filter: blur(8px);
    box-shadow: 0 4px 20px rgba(0,0,0,.3);
}
.keyboard-hint summary {
    cursor: pointer;
    font-weight: 600;
    color: #a8969a;
    margin-bottom: 4px;
    user-select: none;
}
.keyboard-hint kbd {
    background: #2a2225;
    border: 1px solid #3a3234;
    border-radius: 4px;
    padding: 1px 5px;
    font-family: inherit;
    font-size: .9em;
    color: #d4c4c8;
}
.keyboard-hint .shortcut-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 2px 0;
}
.keyboard-hint .shortcut-label {
    color: #8c7b7f;
}

/* ================================================================
   Focus ring overrides — keyboard navigation
   ================================================================ */
:focus-visible {
    outline: 2px solid #b07c84 !important;
    outline-offset: 2px !important;
}
#chat-input textarea:focus-visible {
    border-color: #b07c84 !important;
    box-shadow: 0 0 0 3px rgba(176,124,132,.15) !important;
}

/* ================================================================
   Accessibility — reduce motion
   ================================================================ */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        transition-duration: 0.01ms !important;
    }
}
"""
