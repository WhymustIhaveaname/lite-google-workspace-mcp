from html import escape as html_escape


def success_html(email: str) -> str:
    safe_email = html_escape(email)
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Authentication Successful</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #0f172a, #1e293b, #334155);
            min-height: 100vh;
            display: flex; align-items: center; justify-content: center;
        }}
        .container {{
            background: rgba(255,255,255,0.95); backdrop-filter: blur(10px);
            padding: 60px; border-radius: 20px;
            box-shadow: 0 30px 60px rgba(0,0,0,0.12);
            text-align: center; max-width: 480px; width: 90%;
            animation: slideUp 0.6s ease-out;
        }}
        @keyframes slideUp {{
            from {{ opacity: 0; transform: translateY(20px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .icon {{
            width: 80px; height: 80px; margin: 0 auto 30px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            border-radius: 50%; display: flex; align-items: center; justify-content: center;
            font-size: 40px; color: white;
        }}
        h1 {{
            font-size: 28px; font-weight: 600; margin-bottom: 20px;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }}
        .message {{ font-size: 16px; line-height: 1.6; color: #4a5568; margin-bottom: 20px; }}
        .user-id {{
            font-weight: 600; color: #667eea;
            padding: 4px 12px; background: rgba(102,126,234,0.1); border-radius: 6px;
        }}
        .button {{
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white; padding: 16px 40px; border: none; border-radius: 30px;
            font-size: 16px; cursor: pointer; margin-top: 30px;
            box-shadow: 0 4px 15px rgba(102,126,234,0.3);
        }}
        .auto-close {{ font-size: 13px; color: #a0aec0; margin-top: 30px; }}
    </style>
    <script>
        function tryClose() {{
            window.close();
            setTimeout(function() {{
                var btn = document.querySelector('.button');
                if (btn) btn.textContent = 'You can close this tab manually';
            }}, 500);
        }}
        setTimeout(tryClose, 10000);
    </script>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Authentication Successful</h1>
        <div class="message">
            Authenticated as <span class="user-id">{safe_email}</span>
        </div>
        <div class="message">Credentials saved. You can close this tab.</div>
        <button class="button" onclick="tryClose()">Close Tab</button>
        <div class="auto-close">This tab will close automatically in 10 seconds</div>
    </div>
</body>
</html>"""


def error_html(message: str) -> str:
    safe_msg = html_escape(message)
    return f"""<!DOCTYPE html>
<html>
<head><title>Authentication Error</title></head>
<body style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 40px auto;
             padding: 20px; text-align: center;">
    <h2 style="color: #d32f2f;">Authentication Error</h2>
    <p>{safe_msg}</p>
    <p>You can close this tab and try again.</p>
</body>
</html>"""
