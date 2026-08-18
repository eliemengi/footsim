import pytest
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).parent.parent

def test_pwa_onboarding_html_structure():
    index = (PROJECT_ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    
    # 1. Onboarding-Overlay existiert
    assert '<div id="onboarding-overlay"' in index
    
    # 2. Language-Step existiert
    assert '<div id="onboarding-step-0"' in index
    
    # 3. Account/Gast-Step existiert
    assert '<div id="onboarding-step-1"' in index
    
    # Favorite Team Step existiert
    assert '<div id="onboarding-step-2"' in index

    # 6. Sprache wird vor Account/Gast gerendert (Reihenfolge im DOM)
    pos_overlay = index.find('id="onboarding-overlay"')
    pos_step0 = index.find('id="onboarding-step-0"')
    pos_step1 = index.find('id="onboarding-step-1"')
    pos_step2 = index.find('id="onboarding-step-2"')
    
    assert pos_overlay < pos_step0 < pos_step1 < pos_step2

def test_pwa_onboarding_js_logic():
    script = (PROJECT_ROOT / "static" / "script.js").read_text(encoding="utf-8")
    
    # 4. source=pwa Detection existiert
    assert "new URLSearchParams(window.location.search).get('source') === 'pwa'" in script
    assert "window.matchMedia('(display-mode: standalone)').matches" in script
    assert "window.navigator.standalone === true" in script
    
    # 5. onboarding_completed wird geprüft
    assert "!localStorage.getItem('onboarding_completed')" in script
    assert "localStorage.setItem('onboarding_completed', 'true')" in script
    
    # 7. normale Browserlogik bleibt separat (Overlay wird nur angezeigt, wenn isPWA && nicht completed)
    assert "if (isPWA && !localStorage.getItem('onboarding_completed') && onboardingOverlay) {" in script
    
    # 8. keine konfliktierende style.display-vs-hidden-Logik mehr
    # We should ensure we don't have .style.display = 'flex' inside the PWA block to unhide the overlay
    pwa_block_match = re.search(r'// APP-ONLY ONBOARDING WIZARD(.*)', script, re.DOTALL)
    assert pwa_block_match is not None
    pwa_block = pwa_block_match.group(1)
    
    assert "onboardingOverlay.style.display" not in pwa_block
    assert "step1.style.display" not in pwa_block
    assert "step2.style.display" not in pwa_block
    
    # We must be using show() and hide() instead
    assert "show(onboardingOverlay)" in pwa_block
    assert "hide(onboardingOverlay)" in pwa_block
    assert "show(step1)" in pwa_block
    assert "hide(step0)" in pwa_block

