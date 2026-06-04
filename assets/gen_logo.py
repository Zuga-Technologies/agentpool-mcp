"""Render polished AgentPool logo variants. Edit PALETTES, re-run, eyeball."""
import cairosvg

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <radialGradient id="bg" cx="50%" cy="42%" r="62%">
      <stop offset="0%" stop-color="{BG1}"/>
      <stop offset="100%" stop-color="{BG0}"/>
    </radialGradient>
    <linearGradient id="head" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="{H1}"/>
      <stop offset="55%" stop-color="{H0}"/>
      <stop offset="100%" stop-color="{H2}"/>
    </linearGradient>
    <linearGradient id="headHi" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.32"/>
      <stop offset="40%" stop-color="#ffffff" stop-opacity="0"/>
    </linearGradient>
    <radialGradient id="eye" cx="50%" cy="42%" r="60%">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="38%" stop-color="{EYE1}"/>
      <stop offset="100%" stop-color="{EYE0}"/>
    </radialGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{EYE1}"/>
      <stop offset="100%" stop-color="{EYE0}"/>
    </linearGradient>
    <linearGradient id="sig" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{SIG1}"/>
      <stop offset="100%" stop-color="{SIG0}"/>
    </linearGradient>
    <radialGradient id="pool" cx="50%" cy="38%" r="70%">
      <stop offset="0%" stop-color="{EYE1}" stop-opacity="0.30"/>
      <stop offset="100%" stop-color="{BG0}" stop-opacity="0"/>
    </radialGradient>
    <filter id="glow" x="-70%" y="-70%" width="240%" height="240%">
      <feGaussianBlur stdDeviation="6" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="eyeGlow" x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation="9" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="softShadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="5" stdDeviation="10" flood-color="#000" flood-opacity="0.40"/>
    </filter>
  </defs>

  <!-- background + rim -->
  <circle cx="256" cy="256" r="250" fill="url(#bg)"/>
  <circle cx="256" cy="256" r="250" fill="none" stroke="{H1}" stroke-width="4" opacity="0.5"/>
  <circle cx="256" cy="256" r="236" fill="none" stroke="url(#accent)" stroke-width="1.5" opacity="0.22"/>

  <!-- THE POOL: agent-node network feeding the hub -->
  <ellipse cx="256" cy="378" rx="176" ry="50" fill="url(#pool)"/>
  <g stroke="url(#accent)" stroke-width="2.6" opacity="0.6" stroke-linecap="round" fill="none">
    <line x1="256" y1="320" x2="116" y2="362"/>
    <line x1="256" y1="320" x2="188" y2="398"/>
    <line x1="256" y1="320" x2="256" y2="412"/>
    <line x1="256" y1="320" x2="324" y2="398"/>
    <line x1="256" y1="320" x2="396" y2="362"/>
  </g>
  <g stroke="url(#accent)" stroke-width="1.5" opacity="0.32" stroke-linecap="round" fill="none">
    <line x1="116" y1="362" x2="188" y2="398"/>
    <line x1="188" y1="398" x2="256" y2="412"/>
    <line x1="256" y1="412" x2="324" y2="398"/>
    <line x1="324" y1="398" x2="396" y2="362"/>
  </g>
  <g>
    <circle cx="116" cy="362" r="12" fill="url(#accent)" filter="url(#glow)"/>
    <circle cx="188" cy="398" r="12" fill="url(#accent)" filter="url(#glow)"/>
    <circle cx="256" cy="414" r="15" fill="url(#sig)" filter="url(#glow)"/>
    <circle cx="324" cy="398" r="12" fill="url(#accent)" filter="url(#glow)"/>
    <circle cx="396" cy="362" r="12" fill="url(#accent)" filter="url(#glow)"/>
    <circle cx="256" cy="414" r="24" fill="none" stroke="url(#sig)" stroke-width="2" opacity="0.35"/>
  </g>

  <!-- antenna + share signal -->
  <line x1="256" y1="116" x2="256" y2="68" stroke="{H0}" stroke-width="7" stroke-linecap="round"/>
  <circle cx="256" cy="56" r="14" fill="url(#sig)" filter="url(#glow)"/>
  <path d="M 231 48 Q 222 36 231 24" fill="none" stroke="url(#sig)" stroke-width="2.6" stroke-linecap="round" opacity="0.6"/>
  <path d="M 281 48 Q 290 36 281 24" fill="none" stroke="url(#sig)" stroke-width="2.6" stroke-linecap="round" opacity="0.6"/>

  <!-- side ports -->
  <rect x="118" y="182" width="34" height="64" rx="13" fill="{H2}"/>
  <circle cx="135" cy="214" r="7" fill="url(#accent)" filter="url(#glow)" opacity="0.85"/>
  <rect x="360" y="182" width="34" height="64" rx="13" fill="{H2}"/>
  <circle cx="377" cy="214" r="7" fill="url(#accent)" filter="url(#glow)" opacity="0.85"/>

  <!-- HUB head -->
  <rect x="150" y="118" width="212" height="188" rx="48" ry="48" fill="url(#head)" filter="url(#softShadow)"/>
  <rect x="150" y="118" width="212" height="188" rx="48" ry="48" fill="url(#headHi)"/>
  <rect x="150" y="118" width="212" height="188" rx="48" ry="48" fill="none" stroke="#ffffff" stroke-width="1.5" opacity="0.18"/>

  <!-- visor recess -->
  <rect x="170" y="156" width="172" height="96" rx="40" ry="40" fill="#05060f" opacity="0.55"/>

  <!-- eyes -->
  <ellipse cx="212" cy="200" rx="25" ry="29" fill="url(#eye)" filter="url(#eyeGlow)"/>
  <ellipse cx="300" cy="200" rx="25" ry="29" fill="url(#eye)" filter="url(#eyeGlow)"/>
  <ellipse cx="205" cy="190" rx="5.5" ry="7.5" fill="#fff" opacity="0.95"/>
  <ellipse cx="293" cy="190" rx="5.5" ry="7.5" fill="#fff" opacity="0.95"/>

  <!-- mouth: pool/knowledge bar -->
  <rect x="198" y="262" width="116" height="28" rx="11" fill="#05060f" opacity="0.85"/>
  <circle cx="226" cy="276" r="5" fill="url(#accent)"/>
  <circle cx="256" cy="276" r="5" fill="url(#sig)"/>
  <circle cx="286" cy="276" r="5" fill="url(#accent)"/>
</svg>"""

# H0=mid head, H1=top light, H2=deep/shadow; EYE0/1=eye+accent; SIG0/1=signal node; BG0/1=bg
PALETTES = {
    "teal": dict(H0="#0d9488", H1="#2dd4bf", H2="#0f766e", EYE0="#0891b2", EYE1="#67e8f9",
                 SIG0="#f59e0b", SIG1="#fbbf24", BG0="#03121a", BG1="#0a2230"),
    "amber": dict(H0="#f59e0b", H1="#fbbf24", H2="#b45309", EYE0="#0891b2", EYE1="#67e8f9",
                  SIG0="#22d3ee", SIG1="#67e8f9", BG0="#0a0a1a", BG1="#1a1408"),
    "sky": dict(H0="#0ea5e9", H1="#7dd3fc", H2="#0369a1", EYE0="#0891b2", EYE1="#a5f3fc",
                SIG0="#34d399", SIG1="#6ee7b7", BG0="#04101c", BG1="#0a1e2e"),
}

for name, p in PALETTES.items():
    svg = TEMPLATE
    for k, v in p.items():
        svg = svg.replace("{" + k + "}", v)
    open(f"assets/logo-{name}.svg", "w", encoding="utf-8").write(svg)
    for sz in (512, 64):
        cairosvg.svg2png(bytestring=svg.encode(), write_to=f"assets/logo-{name}-{sz}.png",
                         output_width=sz, output_height=sz)
    print(f"rendered {name}")
