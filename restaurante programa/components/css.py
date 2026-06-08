"""Design system moderno para Restaurante Pro."""

from __future__ import annotations

from html import escape

import streamlit as st


def inject_styles() -> None:
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:wght@400;700&display=swap');
            :root {
                --bg: #f3f2ee;
                --panel: #ffffff;
                --panel-soft: #faf9f6;
                --ink: #1e1c19;
                --muted: #6b655c;
                --line: #ddd7ce;
                --line-strong: #c5bcaf;
                --nav: #1b1916;
                --nav-soft: #2b2823;
                --primary: #c93a2b;
                --primary-hover: #a82e21;
                --primary-soft: rgba(201, 58, 43, 0.08);
                --blue: #2563a0;
                --blue-soft: rgba(37, 99, 160, 0.08);
                --green: #2a7d4f;
                --green-soft: rgba(42, 125, 79, 0.08);
                --amber: #c47f1a;
                --amber-soft: rgba(196, 127, 26, 0.08);
                --danger: #c2332e;
                --danger-soft: rgba(194, 51, 46, 0.08);
                --purple: #6d3f9e;
                --shadow-sm: 0 1px 3px rgba(24, 21, 18, 0.06);
                --shadow-md: 0 4px 12px rgba(24, 21, 18, 0.07);
                --shadow-lg: 0 8px 28px rgba(24, 21, 18, 0.09);
                --radius: 10px;
                --radius-sm: 6px;
                --color-pergamino: #fff9ed;
                --color-cuero: #5d3a2e;
                --color-oro-viejo: #e2dabf;
                --color-borde: #d4b89a;
            }
            #MainMenu, footer, div[data-testid="stToolbar"],
            div[data-testid="stDecoration"] { display: none !important; }
            header[data-testid="stHeader"],
            div[data-testid="stHeader"] {
                background: transparent !important;
                height: 0 !important;
                min-height: 0 !important;
                display: none !important;
            }
            html, body, .stApp {
                background: var(--bg);
                color: var(--ink);
                font-family: 'Libre Caslon Text', Inter, "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
                -webkit-font-smoothing: antialiased;
                -moz-osx-font-smoothing: grayscale;
            }
            .block-container {
                padding-top: 1.2rem;
                padding-bottom: 2rem;
                max-width: 1420px;
            }

            /* Sidebar */
            section[data-testid="stSidebar"] {
                transform: none !important;
                visibility: visible !important;
                min-width: 250px !important;
                width: 250px !important;
                display: flex !important;
                background: var(--nav) !important;
                border-right: 1px solid rgba(255,255,255,0.06);
                overflow-y: auto !important;
                height: 100vh !important;
                position: relative !important;
            }
            section[data-testid="stSidebar"] > div:nth-child(2) {
                overflow-y: auto !important;
                flex: 1 1 auto !important;
                max-height: 100vh !important;
            }
            section[data-testid="stSidebar"]::-webkit-scrollbar {
                width: 5px;
            }
            section[data-testid="stSidebar"]::-webkit-scrollbar-thumb {
                background: rgba(255,255,255,0.15);
                border-radius: 4px;
            }
            section[data-testid="stSidebar"]::-webkit-scrollbar-track {
                background: transparent;
            }
            section[data-testid="stSidebar"] > div:first-child {
                background: var(--nav) !important;
            }
            /* collapsedControl hidden via JS-injected style in parent frame (keep_sidebar_open) */
            section[data-testid="stSidebar"] .st-emotion-cache-1cypcdb,
            section[data-testid="stSidebar"] .st-emotion-cache-6qob1r {
                background: var(--nav) !important;
            }
            section[data-testid="stSidebar"] h1 { display: none; }
            section[data-testid="stSidebar"] p,
            section[data-testid="stSidebar"] label,
            section[data-testid="stSidebar"] span,
            section[data-testid="stSidebar"] .st-emotion-cache-1wbqy5l span {
                color: #e8e4dc !important;
            }
            section[data-testid="stSidebar"] [role="radiogroup"] label {
                border-radius: 8px;
                padding: 0.5rem 0.65rem;
                margin: 0.08rem 0;
                border: 1px solid transparent;
                transition: all 0.2s ease;
                display: flex;
                align-items: center;
                gap: 0.4rem;
            }
            section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
                background: var(--nav-soft);
                border-color: rgba(255,255,255,0.07);
            }
            section[data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] {
                background: rgba(201, 58, 43, 0.15) !important;
                border-color: rgba(201, 58, 43, 0.3) !important;
            }
            section[data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"] span {
                color: #f0e8e0 !important;
                font-weight: 700 !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"] p {
                color: #e8e4dc;
            }
            section[data-testid="stSidebar"] hr {
                border-color: rgba(255,255,255,0.08);
            }
            section[data-testid="stSidebar"] button {
                border-color: rgba(255,255,255,0.15) !important;
                color: #e8e4dc !important;
                background: transparent !important;
            }
            section[data-testid="stSidebar"] button:hover {
                background: var(--nav-soft) !important;
                border-color: var(--primary) !important;
            }

            /* Page header */
            .page-title {
                font-size: 1.55rem;
                font-weight: 800;
                letter-spacing: -0.02em;
                margin: 0;
            }
            .page-subtitle {
                color: var(--muted);
                margin: 0.1rem 0 0.9rem;
                font-size: 0.92rem;
            }
            .app-header {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius);
                padding: 0.9rem 1.1rem;
                margin-bottom: 1rem;
                box-shadow: var(--shadow-sm);
            }

            /* Login "El Patr\u00f3n" (Hacienda Heritage - Vintage) */
            .login-header { text-align: center; margin-bottom: 30px; }
            .login-badge {
                background: #3e2723; color: white; display: inline-block;
                padding: 4px 12px; font-size: 12px; font-weight: bold;
                letter-spacing: 2px; margin-bottom: 10px;
            }
            .login-title { font-size: 32px; color: var(--color-cuero); font-weight: 700; }
            .login-separator { color: var(--color-cuero); font-size: 14px; margin: 10px 0; }
            .login-label {
                display: block; font-size: 12px; font-weight: bold;
                color: #444; margin-bottom: 8px; letter-spacing: 1px;
            }
            .login-input-wrapper { position: relative; margin-bottom: 20px; }
            .login-input {
                width: 100%; padding: 12px 12px 12px 40px;
                background: #f8f1e5; border: 1px solid var(--color-borde);
                border-radius: 4px; font-size: 16px; color: var(--color-cuero);
                box-sizing: border-box;
            }
            .login-icon {
                position: absolute; left: 12px; top: 50%;
                transform: translateY(-50%); opacity: 0.5;
            }
            .login-button-primary {
                width: 100%; background: var(--color-cuero); color: white;
                padding: 14px; border: none; border-radius: 4px;
                font-weight: bold; font-size: 18px; cursor: pointer;
                margin-bottom: 12px; transition: background 0.3s;
            }
            .login-button-primary:hover { background: #3e2723; }
            .login-button-secondary {
                width: 100%; background: transparent; color: var(--color-cuero);
                padding: 12px; border: 1px solid var(--color-borde);
                border-radius: 4px; font-weight: bold; font-size: 14px; cursor: pointer;
            }
            /* Streamlit overrides */
            [data-testid="stAppViewContainer"] .stTextInput { position: relative; }
            [data-testid="stAppViewContainer"] .stTextInput input {
                width: 100% !important; padding: 12px 2.5rem 12px 2.5rem !important;
                background: #f8f1e5 !important; border: 1px solid var(--color-borde) !important;
                border-radius: 4px !important; font-size: 16px !important;
                color: var(--color-cuero) !important;
                font-family: 'Libre Caslon Text', serif !important;
                min-height: unset !important; line-height: 1.4 !important;
            }
            [data-testid="stAppViewContainer"] .stTextInput input:focus {
                border-color: var(--color-cuero) !important;
                box-shadow: 0 0 0 2px rgba(93,58,46,0.15) !important;
            }
            /* Icon wrapper: baseweb container wraps only the input (no label) → correct top:50% */
            [data-testid="stAppViewContainer"] .stTextInput div[data-baseweb="input"] { position: relative; }
            [data-testid="stAppViewContainer"] .stTextInput:first-of-type div[data-baseweb="input"]::before {
                content: "\U0001F464"; position: absolute; left: 12px; top: 50%;
                transform: translateY(-50%); z-index: 1; font-size: 16px;
                opacity: 0.5; line-height: 1; pointer-events: none;
            }
            [data-testid="stAppViewContainer"] .stTextInput:not(:first-of-type) div[data-baseweb="input"]::before {
                content: "\U0001F512"; position: absolute; left: 12px; top: 50%;
                transform: translateY(-50%); z-index: 1; font-size: 16px;
                opacity: 0.5; line-height: 1; pointer-events: none;
            }
            /* Ensure eye toggle on password fields isn't overlapped */
            [data-testid="stAppViewContainer"] .stTextInput input + div,
            [data-testid="stAppViewContainer"] .stTextInput button {
                z-index: 2; position: relative;
            }
            [data-testid="stAppViewContainer"] .stButton button[kind="primary"] {
                width: 100% !important; background: var(--color-cuero) !important;
                color: white !important; padding: 14px !important; border: none !important;
                border-radius: 4px !important; font-weight: bold !important;
                font-size: 18px !important; cursor: pointer !important;
                margin-bottom: 12px !important; transition: background 0.3s !important;
                font-family: 'Libre Caslon Text', serif !important;
                min-height: unset !important; line-height: 1.4 !important;
            }
            [data-testid="stAppViewContainer"] .stButton button[kind="primary"]:hover {
                background: #3e2723 !important;
            }
            [data-testid="stAppViewContainer"] .stButton button:not([kind="primary"]) {
                width: 100% !important; background: transparent !important;
                color: var(--color-cuero) !important; padding: 12px !important;
                border: 1px solid var(--color-borde) !important;
                border-radius: 4px !important; font-weight: bold !important;
                font-size: 14px !important; cursor: pointer !important;
                font-family: 'Libre Caslon Text', serif !important;
                min-height: unset !important; line-height: 1.4 !important;
            }
            [data-testid="stAppViewContainer"] .stButton button:not([kind="primary"]):hover {
                border-color: var(--color-cuero) !important;
            }
            .login-footer { text-align: center; margin-top: 40px; font-size: 12px; color: #888; border-top: 1px solid var(--color-borde); padding-top: 20px; }
            .footer-links a { color: #888; text-decoration: none; margin: 0 4px; }
            .footer-links a:hover { color: var(--color-cuero); text-decoration: underline; }
            .active-users { margin-top: 10px; color: var(--color-cuero); }

            /* Cards */
            .card {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius);
                padding: 0.95rem;
                box-shadow: var(--shadow-sm);
                margin-bottom: 0.7rem;
                transition: box-shadow 0.2s ease;
            }
            .card:hover {
                box-shadow: var(--shadow-md);
            }

            /* Terminal bar */
            .terminal-bar {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 1rem;
                background: linear-gradient(135deg, var(--ink) 0%, #2d2924 100%);
                color: white;
                border-radius: var(--radius);
                padding: 0.85rem 1rem;
                margin-bottom: 0.85rem;
                box-shadow: var(--shadow-md);
            }
            .terminal-title {
                font-size: 1.3rem;
                font-weight: 850;
                line-height: 1.1;
            }
            .terminal-sub {
                color: #d4cdc2;
                font-size: 0.88rem;
                margin-top: 0.15rem;
            }
            .terminal-chip {
                border: 1px solid rgba(255,255,255,0.18);
                background: rgba(255,255,255,0.07);
                border-radius: 999px;
                padding: 0.35rem 0.75rem;
                font-weight: 760;
                white-space: nowrap;
                font-size: 0.88rem;
            }

            /* KPI Premium Cards */
            .stat-card {
                background: var(--panel);
                border: 1px solid var(--line);
                border-left: 4px solid var(--blue);
                border-radius: var(--radius);
                padding: 0.85rem 0.9rem;
                box-shadow: var(--shadow-sm);
                min-height: 82px;
                transition: all 0.25s ease;
                position: relative;
                overflow: hidden;
            }
            .stat-card::after {
                content: '';
                position: absolute;
                top: 0;
                right: 0;
                width: 48px;
                height: 48px;
                border-radius: 0 0 0 48px;
                background: rgba(0,0,0,0.02);
            }
            .stat-card:hover {
                box-shadow: var(--shadow-md);
                transform: translateY(-2px);
            }
            .stat-label {
                color: var(--muted);
                font-size: 0.75rem;
                font-weight: 760;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 0.15rem;
            }
            .stat-value {
                font-size: 1.55rem;
                font-weight: 850;
                line-height: 1.15;
                letter-spacing: -0.02em;
            }

            /* KPI Metric override */
            div[data-testid="stMetric"] {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius);
                padding: 0.7rem 0.85rem;
                box-shadow: var(--shadow-sm);
                transition: all 0.25s ease;
            }
            div[data-testid="stMetric"]:hover {
                box-shadow: var(--shadow-md);
                transform: translateY(-1px);
            }
            div[data-testid="stMetric"] > div:first-child {
                font-size: 0.82rem !important;
                color: var(--muted) !important;
                font-weight: 600 !important;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            div[data-testid="stMetric"] > div:nth-child(2) {
                font-size: 1.6rem !important;
                font-weight: 850 !important;
                letter-spacing: -0.02em;
            }

            /* Product tiles */
            .product-tile {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                padding: 0.72rem 0.85rem;
                min-height: 68px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                box-shadow: var(--shadow-sm);
                transition: all 0.2s ease;
            }
            .product-tile:hover {
                border-color: var(--primary);
                box-shadow: 0 0 0 2px var(--primary-soft);
            }
            .product-name {
                font-weight: 820;
                font-size: 0.95rem;
                line-height: 1.2;
            }
            .product-price {
                color: var(--muted);
                font-size: 0.88rem;
                margin-top: 0.15rem;
            }

            /* Waiter chips */
            .waiter-strip {
                display: grid;
                grid-template-columns: repeat(4, minmax(0, 1fr));
                gap: 0.6rem;
                margin-bottom: 0.85rem;
            }
            .waiter-chip {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                padding: 0.65rem 0.72rem;
                box-shadow: var(--shadow-sm);
                transition: all 0.2s ease;
            }
            .waiter-chip:hover {
                box-shadow: var(--shadow-md);
            }
            .waiter-chip-label {
                color: var(--muted);
                font-size: 0.75rem;
                font-weight: 780;
                text-transform: uppercase;
                letter-spacing: 0.04em;
            }
            .waiter-chip-value {
                font-size: 1.2rem;
                font-weight: 880;
                line-height: 1.15;
            }

            /* Table cards */
            .table-card {
                background: var(--panel);
                border: 1px solid var(--line);
                border-left: 5px solid #9a958c;
                border-radius: var(--radius-sm);
                padding: 0.78rem;
                min-height: 118px;
                box-shadow: var(--shadow-sm);
                margin-bottom: 0.5rem;
                transition: all 0.25s ease;
            }
            .table-card:hover {
                box-shadow: var(--shadow-md);
            }
            .table-card.free { border-left-color: #8f8a82; background: #f8f7f4; }
            .table-card.busy { border-left-color: var(--blue); }
            .table-card.bill { border-left-color: var(--amber); background: #fff8e8; }
            .table-card-num { font-size: 1.3rem; font-weight: 900; line-height: 1.1; }
            .table-card-meta {
                display: flex;
                justify-content: space-between;
                gap: 0.6rem;
                color: var(--muted);
                font-size: 0.84rem;
                margin-top: 0.25rem;
            }

            /* Ready order */
            .ready-order {
                background: #eff8f2;
                border: 1px solid #bad8c5;
                border-radius: var(--radius-sm);
                padding: 0.6rem 0.72rem;
                margin-bottom: 0.4rem;
                transition: all 0.2s ease;
            }
            .ready-order:hover {
                background: #e5f3e8;
            }

            /* Note presets */
            .note-preset {
                display: inline-flex;
                margin: 0.1rem 0.12rem 0.1rem 0;
                padding: 0.2rem 0.4rem;
                border-radius: 999px;
                border: 1px solid var(--line);
                color: var(--muted);
                font-size: 0.76rem;
                font-weight: 760;
                transition: all 0.15s ease;
                cursor: default;
            }
            .note-preset:hover {
                border-color: var(--primary);
                color: var(--primary);
                background: var(--primary-soft);
            }

            /* Qty badge */
            .qty-badge {
                display: flex;
                align-items: center;
                justify-content: center;
                height: 2.6rem;
                min-width: 2.8rem;
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                background: var(--panel-soft);
                font-size: 1.2rem;
                font-weight: 850;
            }

            /* Cart panel */
            .cart-panel {
                position: sticky;
                top: 0.8rem;
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius);
                padding: 0.9rem;
                box-shadow: var(--shadow-sm);
            }
            .cart-title {
                font-size: 1.2rem;
                font-weight: 850;
                margin-bottom: 0.5rem;
            }

            /* KDS Kitchen */
            .kds-summary {
                background: var(--panel);
                border: 1px solid var(--line);
                border-left: 5px solid var(--blue);
                border-radius: var(--radius-sm);
                padding: 0.8rem;
                box-shadow: var(--shadow-sm);
                margin-bottom: 0.7rem;
            }
            .kds-summary-title {
                font-size: 0.8rem;
                font-weight: 820;
                color: var(--muted);
                text-transform: uppercase;
                letter-spacing: 0.04em;
                margin-bottom: 0.4rem;
            }
            .kds-summary-line {
                display: flex;
                justify-content: space-between;
                gap: 0.7rem;
                padding: 0.28rem 0;
                border-bottom: 1px solid #ece6dd;
                font-weight: 760;
            }
            .kds-card {
                background: var(--panel);
                border: 2px solid var(--green);
                border-radius: var(--radius-sm);
                padding: 0.72rem;
                box-shadow: var(--shadow-sm);
                margin-bottom: 0.75rem;
                transition: all 0.2s ease;
            }
            .kds-card:hover {
                box-shadow: var(--shadow-md);
            }
            .kds-card.warn { border-color: var(--amber); }
            .kds-card.critical {
                border-color: var(--danger);
                border-width: 4px;
                animation: criticalPulse 1.45s ease-in-out infinite;
            }
            @keyframes criticalPulse {
                0%, 100% { box-shadow: var(--shadow-sm); }
                50% { box-shadow: 0 0 0 4px rgba(194, 51, 46, 0.15), var(--shadow-sm); }
            }
            .kds-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 0.6rem;
                padding-bottom: 0.5rem;
                border-bottom: 1px solid var(--line);
                margin-bottom: 0.45rem;
                font-weight: 850;
            }
            .kds-time {
                border-radius: 999px;
                background: var(--ink);
                color: white;
                padding: 0.2rem 0.5rem;
                font-size: 0.8rem;
                white-space: nowrap;
            }

            /* Dish rows */
            .dish-row {
                display: grid;
                grid-template-columns: 2.8rem minmax(0, 1fr);
                gap: 0.5rem;
                align-items: start;
                padding: 0.45rem 0;
                border-bottom: 1px solid #efeae2;
            }
            .dish-qty {
                display: inline-flex;
                justify-content: center;
                align-items: center;
                min-height: 2.3rem;
                border-radius: var(--radius-sm);
                background: var(--ink);
                color: white;
                font-size: 1.2rem;
                font-weight: 900;
            }
            .dish-name {
                font-size: 0.95rem;
                font-weight: 820;
                line-height: 1.22;
            }
            .dish-note {
                margin-top: 0.3rem;
                padding: 0.35rem 0.42rem;
                background: #fff0d6;
                border-left: 3px solid var(--amber);
                border-radius: var(--radius-sm);
                color: #5f3b0b;
                font-weight: 700;
                font-size: 0.85rem;
            }

            /* Cash / Pay */
            .cash-table {
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                background: var(--panel);
                padding: 0.58rem;
                margin-bottom: 0.5rem;
                box-shadow: var(--shadow-sm);
                transition: all 0.2s ease;
            }
            .cash-table:hover {
                box-shadow: var(--shadow-md);
            }
            .cash-table.free { border-left: 5px solid #9a958c; background: #f6f5f1; }
            .cash-table.eating { border-left: 5px solid var(--blue); }
            .cash-table.bill {
                border-left: 5px solid var(--amber);
                animation: billPulse 1.6s ease-in-out infinite;
            }
            @keyframes billPulse {
                0%, 100% { background: var(--panel); }
                50% { background: #fff6df; }
            }
            .cash-table-num { font-size: 1rem; font-weight: 850; }
            .cash-table-meta { color: var(--muted); font-size: 0.8rem; margin-top: 0.1rem; }
            .pay-panel {
                position: sticky;
                top: 0.75rem;
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius);
                padding: 0.8rem;
                box-shadow: var(--shadow-sm);
            }
            .pay-title { font-size: 1.1rem; font-weight: 850; margin-bottom: 0.5rem; }
            .change-box {
                background: #eef7f1;
                border: 1px solid #b9d8c4;
                border-radius: var(--radius-sm);
                padding: 0.75rem;
                margin-top: 0.55rem;
            }
            .change-label {
                color: #31583d;
                font-weight: 760;
                font-size: 0.8rem;
            }
            .change-value {
                font-size: 1.55rem;
                font-weight: 900;
                color: #174428;
                line-height: 1.1;
            }
            .history-row {
                display: flex;
                justify-content: space-between;
                gap: 0.7rem;
                border-bottom: 1px solid #ece6dd;
                padding: 0.4rem 0;
                font-size: 0.88rem;
                transition: background 0.15s ease;
            }
            .history-row:hover {
                background: var(--panel-soft);
            }

            /* Mesa cards */
            .mesa {
                background: var(--panel);
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                padding: 0.95rem;
                min-height: 125px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                box-shadow: var(--shadow-sm);
                transition: all 0.25s ease;
            }
            .mesa:hover {
                box-shadow: var(--shadow-md);
            }
            .mesa-num { font-size: 1.45rem; font-weight: 850; letter-spacing: 0; }

            .muted { color: var(--muted); font-size: 0.88rem; }

            /* Pill badges */
            .pill {
                display: inline-flex;
                align-items: center;
                border-radius: 999px;
                padding: 0.25rem 0.62rem;
                color: white;
                font-size: 0.76rem;
                font-weight: 760;
                width: fit-content;
                white-space: nowrap;
            }

            /* Line items */
            .line {
                display: flex;
                justify-content: space-between;
                gap: 0.7rem;
                border-bottom: 1px solid #ece6dd;
                padding: 0.55rem 0;
                transition: background 0.15s ease;
            }
            .line:hover {
                background: var(--panel-soft);
            }
            .total {
                background: linear-gradient(135deg, var(--ink) 0%, #2d2924 100%);
                color: white;
                border-radius: var(--radius-sm);
                display: flex;
                justify-content: space-between;
                padding: 0.9rem 1rem;
                margin-top: 0.75rem;
                font-weight: 800;
            }
            .ticket {
                font-family: ui-monospace, Consolas, monospace;
                white-space: pre-wrap;
                background: #fffdf8;
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                padding: 0.95rem;
                box-shadow: inset 0 0 0 1px rgba(0,0,0,0.02);
            }

            /* Buttons */
            .stButton > button,
            .stDownloadButton > button,
            button[data-testid="baseButton-secondary"] {
                border-radius: 8px !important;
                border: 1px solid var(--line-strong) !important;
                background: #fffdf8 !important;
                color: #1f1b16 !important;
                box-shadow: none !important;
                font-weight: 700 !important;
                min-height: 2.45rem;
                opacity: 1 !important;
                transition: all 0.15s ease !important;
            }
            .stButton > button:hover,
            .stDownloadButton > button:hover,
            button[data-testid="baseButton-secondary"]:hover {
                border-color: var(--primary) !important;
                color: var(--primary) !important;
                background: var(--primary-soft) !important;
                box-shadow: 0 2px 8px rgba(201, 58, 43, 0.12) !important;
                transform: translateY(-1px);
            }
            .stButton > button:active,
            .stDownloadButton > button:active {
                transform: translateY(0) !important;
            }
            button[data-testid="baseButton-primary"],
            .stButton > button[kind="primary"] {
                background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%) !important;
                border-color: var(--primary) !important;
                color: white !important;
                box-shadow: 0 2px 8px rgba(201, 58, 43, 0.2) !important;
            }
            button[data-testid="baseButton-primary"]:hover,
            .stButton > button[kind="primary"]:hover {
                background: linear-gradient(135deg, var(--primary-hover) 0%, #8f281d 100%) !important;
                color: white !important;
                box-shadow: 0 4px 12px rgba(201, 58, 43, 0.3) !important;
                transform: translateY(-1px);
            }
            .stButton > button[kind="primary"]:active,
            button[data-testid="baseButton-primary"]:active {
                transform: translateY(0) !important;
            }
            .stButton > button:disabled,
            .stDownloadButton > button:disabled,
            button[data-testid="baseButton-secondary"]:disabled,
            button[data-testid="baseButton-primary"]:disabled {
                background: #e6e0d7 !important;
                border-color: #d1c7bb !important;
                color: #736b61 !important;
                cursor: not-allowed !important;
                opacity: 1 !important;
                box-shadow: none !important;
                transform: none !important;
            }
            div[data-testid="stFormSubmitButton"] button {
                background: linear-gradient(135deg, var(--primary) 0%, var(--primary-hover) 100%) !important;
                border-color: var(--primary) !important;
                color: white !important;
                box-shadow: 0 2px 8px rgba(201, 58, 43, 0.2) !important;
            }
            div[data-testid="stFormSubmitButton"] button:hover {
                box-shadow: 0 4px 12px rgba(201, 58, 43, 0.3) !important;
            }

            /* Input fields */
            input, textarea, select,
            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div {
                border-radius: 8px !important;
                background: var(--panel) !important;
                color: var(--ink) !important;
                border-color: var(--line-strong) !important;
                transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
            }
            input:focus, textarea:focus, select:focus {
                border-color: var(--primary) !important;
                box-shadow: 0 0 0 3px var(--primary-soft) !important;
            }
            div[data-baseweb="select"] span, input, textarea { color: var(--ink) !important; }
            .stSelectbox label, .stTextInput label, .stNumberInput label,
            .stDateInput label, .stFileUploader label {
                color: var(--ink) !important;
                font-weight: 760 !important;
            }
            section[data-testid="stSidebar"] .stSelectbox label,
            section[data-testid="stSidebar"] .stTextInput label,
            section[data-testid="stSidebar"] .stNumberInput label {
                color: #e8e4dc !important;
            }

            /* DataFrames */
            div[data-testid="stDataFrame"],
            div[data-testid="stDataEditor"] {
                border: 1px solid var(--line);
                border-radius: var(--radius-sm);
                overflow: hidden;
                box-shadow: var(--shadow-sm);
                background: var(--panel);
                transition: box-shadow 0.2s ease;
            }
            div[data-testid="stDataFrame"]:hover,
            div[data-testid="stDataEditor"]:hover {
                box-shadow: var(--shadow-md);
            }

            /* Tabs */
            .stTabs [data-baseweb="tab-list"] {
                gap: 0.35rem;
                border-bottom: 1px solid var(--line);
                padding: 0 0.25rem;
            }
            .stTabs [data-baseweb="tab"] {
                border-radius: 8px 8px 0 0;
                padding: 0.55rem 0.9rem;
                font-weight: 700;
                font-size: 0.9rem;
                transition: all 0.15s ease;
            }
            .stTabs [data-baseweb="tab"]:hover {
                background: var(--primary-soft);
                color: var(--primary);
            }
            .stTabs [aria-selected="true"] {
                background: var(--panel) !important;
                border-bottom: 2px solid var(--primary) !important;
                color: var(--primary) !important;
            }

            /* Alert */
            .stAlert {
                border-radius: var(--radius-sm);
                border-left: 4px solid;
            }

            /* Expander */
            .streamlit-expanderHeader {
                font-weight: 700 !important;
                border-radius: var(--radius-sm) !important;
                transition: background 0.15s ease !important;
            }
            .streamlit-expanderHeader:hover {
                background: var(--primary-soft) !important;
            }

            /* Kanban board (cocina) */
            .kb-col {
                border-radius: var(--radius) !important;
                padding: 0.65rem 0.7rem 1rem;
                min-height: 120px;
            }

            /* Urgency pulse for tables awaiting bill */
            @keyframes tableUrgent {
                0%, 100% { box-shadow: 0 0 0 0 rgba(196, 127, 26, 0.3); }
                50% { box-shadow: 0 0 0 6px rgba(196, 127, 26, 0); }
            }
            .table-urgent {
                animation: tableUrgent 1.8s ease-in-out infinite !important;
                border-color: var(--amber) !important;
            }
            .table-urgent .table-card-num { color: var(--amber); }

            /* KDS loading spinner */
            @keyframes btnBusy {
                0% { opacity: 1; }
                50% { opacity: 0.6; }
                100% { opacity: 1; }
            }
            button.kds-busy {
                animation: btnBusy 0.8s ease-in-out infinite !important;
                pointer-events: none !important;
                position: relative;
            }
            button.kds-busy::after {
                content: " \\25B6";
                font-size: 0.7rem;
                margin-left: 0.3rem;
            }

            /* Offline mode banner */
            .offline-banner {
                background: linear-gradient(135deg, #fff3dc 0%, #ffe8bf 100%);
                border: 1px solid #e6c78a;
                border-left: 5px solid var(--amber);
                border-radius: var(--radius-sm);
                padding: 0.65rem 0.85rem;
                margin-bottom: 0.7rem;
                display: flex;
                align-items: center;
                gap: 0.55rem;
                font-weight: 700;
                color: #7a5200;
                font-size: 0.88rem;
            }
            .offline-banner::before {
                content: "\\26A0";
                font-size: 1.2rem;
            }

            /* Fade transitions for KDS columns */
            .kds-card {
                transition: opacity 0.35s ease, transform 0.3s ease, box-shadow 0.2s ease !important;
            }
            .kds-card.fade-out {
                opacity: 0;
                transform: translateX(20px);
            }

            /* Responsive */
            @media (max-width: 760px) {
                .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
                .page-title { font-size: 1.32rem; }
                .stat-value { font-size: 1.32rem; }
                .mesa { min-height: 108px; }
                .mesa-num { font-size: 1.32rem; }
                .line { flex-direction: column; gap: 0.25rem; }
                div[data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: 0.45rem; }
                div[data-testid="column"] { min-width: min(100%, 260px); flex: 1 1 100% !important; }
                .stButton > button, .stDownloadButton > button { min-height: 3.15rem; font-size: 1rem; }
                div[data-testid="stTextInput"] input,
                div[data-testid="stNumberInput"] input,
                div[data-testid="stSelectbox"] div[data-baseweb="select"] { min-height: 3rem; }
                .terminal-bar { flex-direction: column; align-items: flex-start; }
                .terminal-chip { width: 100%; text-align: center; }
                .waiter-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
                .cart-panel { position: static; margin-top: 1rem; }
                .pay-panel { position: static; }
                .kds-head { align-items: flex-start; flex-direction: column; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def terminal_mode_styles() -> None:
    if not st.session_state.get("terminal_lock"):
        return
    terminal = st.session_state.terminal_lock
    color_accent = "var(--blue)"
    if terminal == "Mozo":
        color_accent = "#2563a0"
    elif terminal == "Cocina":
        color_accent = "#c47f1a"
    elif terminal == "Caja":
        color_accent = "#2a7d4f"

    st.markdown(
        f"""
        <style>
            /* Full-screen: ocultar sidebar y todo el chrome de admin */
            section[data-testid="stSidebar"],
            div[data-testid="collapsedControl"],
            header[data-testid="stHeader"],
            #MainMenu, footer, div[data-testid="stToolbar"],
            div[data-testid="stDecoration"] {{
                display: none !important;
            }}
            .stApp {{
                background: var(--bg);
            }}
            .block-container {{
                max-width: 1280px;
                padding:
                    0.5rem 0.7rem 0.5rem 0.7rem !important;
            }}
            div[data-testid="stAppViewContainer"] > .main {{
                padding-top: 0 !important;
            }}
            /* Terminal indicator bar */
            .stApp::before {{
                content: "{terminal}";
                position: fixed;
                bottom: 0.4rem;
                right: 0.6rem;
                font-size: 0.7rem;
                font-weight: 800;
                color: {color_accent};
                opacity: 0.3;
                text-transform: uppercase;
                letter-spacing: 0.1em;
                pointer-events: none;
                z-index: 9999;
            }}
            @media print {{
                .stApp::before {{ display: none; }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def title(text: str, subtitle: str = "") -> None:
    if st.session_state.get("terminal_lock"):
        st.markdown(
            f"""
            <div class="terminal-bar">
                <div>
                    <div class="terminal-title">{escape(text)}</div>
                    <div class="terminal-sub">{escape(subtitle)}</div>
                </div>
                <div class="terminal-chip">{escape(st.session_state.terminal_lock)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        f"""
        <div class="app-header">
            <div class="page-title">{escape(text)}</div>
            <div class="page-subtitle">{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str | int | float, accent: str = "#2563a0") -> None:
    st.markdown(
        f"""
        <div class="stat-card" style="border-left-color:{accent}">
            <div class="stat-label">{escape(str(label))}</div>
            <div class="stat-value">{escape(str(value))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def offline_banner() -> None:
    """Muestra un banner elegante si la app opera en modo SQLite local (sin Supabase)."""
    try:
        from database import using_postgres
        if using_postgres():
            return
    except Exception:
        pass
    st.markdown(
        '<div class="offline-banner">Modo local seguro &mdash; '
        'los datos se guardan en SQLite. Conecta DATABASE_URL para activar Supabase.</div>',
        unsafe_allow_html=True,
    )


def auto_refresh(seconds: int) -> None:
    """Soft auto-refresh that preserves widget state by using st.rerun().
    This avoids full page reload (location.reload) which would clear all inputs.
    """
    placeholder = st.empty()
    tick = st.session_state.setdefault("_refresh_tick", 0)
    if tick % 2 == 0:
        placeholder.markdown(
            f'<div style="font-size:0.75rem;color:#999;text-align:right">'
            f'Actualizando en {seconds}s &middot; '
            f'<span style="cursor:pointer;text-decoration:underline" '
            f'onclick="window.parent.location.reload()">forzar</span></div>',
            unsafe_allow_html=True,
        )
    else:
        placeholder.empty()
    st.session_state["_refresh_tick"] = int(st.session_state.get("_last_refresh_at", 0))
    import time as _t
    now = _t.time()
    last = float(st.session_state.get("_last_refresh_at", 0))
    if now - last >= seconds:
        st.session_state["_last_refresh_at"] = now
        st.session_state["_refresh_tick"] = int(st.session_state.get("_refresh_tick", 0)) + 1
        st.rerun()
