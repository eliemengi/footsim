# -*- coding: utf-8 -*-
import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

replacement = '''            <div id="auth-logged-out-view">
                <section class="drawer-section">
                    <h3 class="drawer-section-title">Login</h3>
                    <form id="login-form" class="auth-form" style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="email" id="login-email" placeholder="Email" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <input type="password" id="login-password" placeholder="Password" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <button type="submit" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--primary-color); color: white; border: none; cursor: pointer;">Login</button>
                    </form>
                    <p id="login-error" class="hidden" style="color: var(--danger-color); font-size: 0.85rem; margin-top: 4px;"></p>
                    <div style="margin-top: 8px; text-align: right;">
                        <button type="button" id="show-forgot-btn" style="background: none; border: none; color: var(--text-muted); text-decoration: underline; cursor: pointer; font-size: 0.85rem; padding: 0;">Passwort vergessen?</button>
                    </div>
                </section>
                
                <section class="drawer-section">
                    <h3 class="drawer-section-title">Register</h3>
                    <form id="register-form" class="auth-form" style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="text" id="register-first" placeholder="First Name" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <input type="text" id="register-last" placeholder="Last Name" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <input type="email" id="register-email" placeholder="Email" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <input type="password" id="register-password" placeholder="Password" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <button type="submit" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--primary-color); color: white; border: none; cursor: pointer;">Register</button>
                    </form>
                    <p id="register-error" class="hidden" style="color: var(--danger-color); font-size: 0.85rem; margin-top: 4px;"></p>
                    <p id="register-success" class="hidden" style="color: var(--success-color); font-size: 0.85rem; margin-top: 4px;"></p>
                </section>
            </div>

            <div id="forgot-password-view" class="hidden">
                <section class="drawer-section">
                    <h3 class="drawer-section-title">Passwort vergessen?</h3>
                    <form id="forgot-password-form" class="auth-form" style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="email" id="forgot-email" placeholder="Email" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <button type="submit" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--primary-color); color: white; border: none; cursor: pointer;">Link senden</button>
                        <button type="button" id="forgot-cancel-btn" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--bg-surface); color: var(--text-color); border: 1px solid var(--border-color); cursor: pointer;">Zurück</button>
                    </form>
                    <p id="forgot-message" class="hidden" style="font-size: 0.85rem; margin-top: 4px;"></p>
                </section>
            </div>

            <div id="reset-password-view" class="hidden">
                <section class="drawer-section">
                    <h3 class="drawer-section-title">Neues Passwort vergeben</h3>
                    <form id="reset-password-form" class="auth-form" style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="hidden" id="reset-token">
                        <input type="password" id="reset-new-password" placeholder="Neues Passwort" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <button type="submit" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--primary-color); color: white; border: none; cursor: pointer;">Passwort speichern</button>
                        <button type="button" id="reset-cancel-btn" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--bg-surface); color: var(--text-color); border: 1px solid var(--border-color); cursor: pointer;">Abbrechen / Zum Login</button>
                    </form>
                    <p id="reset-message" class="hidden" style="font-size: 0.85rem; margin-top: 4px;"></p>
                </section>
            </div>
            
            <div id="auth-logged-in-view" class="hidden">
                <section class="drawer-section">
                    <h3 class="drawer-section-title">Profile</h3>
                    <p>Logged in as <strong id="profile-name"></strong></p>
                    <p id="profile-email" style="font-size: 0.9rem; color: var(--text-muted);"></p>
                    <div id="profile-unverified-warning" class="hidden" style="color: var(--warning-color); font-size: 0.85rem; margin-top: 4px;">
                        Email nicht bestätigt.
                        <button type="button" id="resend-verification-btn" style="background: none; border: none; color: var(--primary-color); text-decoration: underline; cursor: pointer; padding: 0; margin-left: 4px;">Bestätigungslink erneut senden</button>
                    </div>
                    <p id="resend-message" class="hidden" style="font-size: 0.85rem; margin-top: 4px;"></p>
                    
                    <button type="button" id="logout-btn" class="submit-btn" style="margin-top: 16px; padding: 8px; border-radius: 4px; background: var(--bg-surface); color: var(--text-color); border: 1px solid var(--border-color); cursor: pointer; width: 100%;">Logout</button>
                </section>

                <section class="drawer-section" style="margin-top: 16px;">
                    <h3 class="drawer-section-title">Passwort ändern</h3>
                    <form id="change-password-form" class="auth-form" style="display: flex; flex-direction: column; gap: 8px;">
                        <input type="password" id="change-current-password" placeholder="Aktuelles Passwort" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <input type="password" id="change-new-password" placeholder="Neues Passwort" required style="padding: 8px; border-radius: 4px; border: 1px solid var(--border-color); background: var(--bg-color); color: var(--text-color);">
                        <button type="submit" class="submit-btn" style="padding: 8px; border-radius: 4px; background: var(--primary-color); color: white; border: none; cursor: pointer;">Ändern</button>
                    </form>
                    <p id="change-password-message" class="hidden" style="font-size: 0.85rem; margin-top: 4px;"></p>
                </section>
            </div>'''

start_marker = '            <div id="auth-logged-out-view">'
end_marker = '            </div>\n            \n        </div>'

import sys
start_idx = content.find(start_marker)
if start_idx == -1:
    print('Start marker not found')
    sys.exit(1)

end_idx = content.find(end_marker, start_idx)
if end_idx == -1:
    print('End marker not found')
    sys.exit(1)

new_content = content[:start_idx] + replacement + '\n' + content[end_idx:]

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Successfully patched index.html')
