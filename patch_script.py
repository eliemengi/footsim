# -*- coding: utf-8 -*-
import re

with open('static/script.js', 'r', encoding='utf-8') as f:
    content = f.read()

replacement = '''// Form logic
const loginForm = el('login-form');
const registerForm = el('register-form');
const logoutBtn = el('logout-btn');

const forgotPasswordView = el('forgot-password-view');
const resetPasswordView = el('reset-password-view');
const loggedOutView = el('auth-logged-out-view');
const loggedInView = el('auth-logged-in-view');

const showForgotBtn = el('show-forgot-btn');
const forgotCancelBtn = el('forgot-cancel-btn');
const forgotForm = el('forgot-password-form');
const forgotMessage = el('forgot-message');

const resetCancelBtn = el('reset-cancel-btn');
const resetForm = el('reset-password-form');
const resetTokenInput = el('reset-token');
const resetMessage = el('reset-message');

const resendBtn = el('resend-verification-btn');
const resendMessage = el('resend-message');
const changePasswordForm = el('change-password-form');
const changePasswordMessage = el('change-password-message');

async function checkAuth() {
    try {
        const res = await fetch('/api/auth/me');
        if (!res.ok) return;
        const data = await res.json();
        
        // Hide all views by default
        hide(loggedOutView);
        hide(forgotPasswordView);
        hide(resetPasswordView);
        hide(loggedInView);
        hide(resendMessage);
        hide(changePasswordMessage);
        
        if (data.authenticated) {
            show(loggedInView);
            el('profile-name').textContent = ${data.user.first_name} ;
            if (el('profile-email')) {
                el('profile-email').textContent = data.user.email;
            }
            if (!data.user.is_verified) {
                show(el('profile-unverified-warning'));
            } else {
                hide(el('profile-unverified-warning'));
            }
        } else {
            // Check if there is a reset token in URL
            const params = new URLSearchParams(window.location.search);
            if (params.has('reset_token')) {
                show(resetPasswordView);
                resetTokenInput.value = params.get('reset_token');
                openAuthDrawer();
                // Clean up URL without reload
                window.history.replaceState({}, document.title, window.location.pathname);
            } else {
                show(loggedOutView);
            }
        }
    } catch(err) {
        console.error(err);
    }
}

if (showForgotBtn) {
    showForgotBtn.addEventListener('click', () => {
        hide(loggedOutView);
        show(forgotPasswordView);
        hide(forgotMessage);
        forgotForm.reset();
    });
}

if (forgotCancelBtn) {
    forgotCancelBtn.addEventListener('click', () => {
        hide(forgotPasswordView);
        show(loggedOutView);
    });
}

if (resetCancelBtn) {
    resetCancelBtn.addEventListener('click', () => {
        hide(resetPasswordView);
        show(loggedOutView);
    });
}

if (forgotForm) {
    forgotForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(forgotMessage);
        
        try {
            const res = await fetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    email: el('forgot-email').value
                })
            });
            const data = await res.json();
            forgotMessage.textContent = data.message || 'Link gesendet.';
            forgotMessage.style.color = res.ok ? 'var(--success-color)' : 'var(--danger-color)';
            show(forgotMessage);
            if (res.ok) forgotForm.reset();
        } catch(err) {
            forgotMessage.textContent = 'Netzwerkfehler';
            forgotMessage.style.color = 'var(--danger-color)';
            show(forgotMessage);
        }
    });
}

if (resetForm) {
    resetForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(resetMessage);
        
        try {
            const res = await fetch('/api/auth/reset-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    token: resetTokenInput.value,
                    new_password: el('reset-new-password').value
                })
            });
            const data = await res.json();
            if (!res.ok) {
                resetMessage.textContent = data.error || 'Fehler beim Zurücksetzen';
                resetMessage.style.color = 'var(--danger-color)';
                show(resetMessage);
            } else {
                resetMessage.textContent = data.message;
                resetMessage.style.color = 'var(--success-color)';
                show(resetMessage);
                resetForm.reset();
                setTimeout(() => {
                    hide(resetPasswordView);
                    show(loggedOutView);
                }, 2000);
            }
        } catch(err) {
            resetMessage.textContent = 'Netzwerkfehler';
            resetMessage.style.color = 'var(--danger-color)';
            show(resetMessage);
        }
    });
}

if (resendBtn) {
    resendBtn.addEventListener('click', async () => {
        hide(resendMessage);
        resendBtn.disabled = true;
        
        try {
            const res = await fetch('/api/auth/resend-verification', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            const data = await res.json();
            resendMessage.textContent = data.message || 'Bestätigungslink gesendet.';
            resendMessage.style.color = res.ok ? 'var(--success-color)' : 'var(--danger-color)';
            show(resendMessage);
        } catch(err) {
            resendMessage.textContent = 'Netzwerkfehler';
            resendMessage.style.color = 'var(--danger-color)';
            show(resendMessage);
        } finally {
            resendBtn.disabled = false;
        }
    });
}

if (changePasswordForm) {
    changePasswordForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(changePasswordMessage);
        
        try {
            const res = await fetch('/api/auth/change-password', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    current_password: el('change-current-password').value,
                    new_password: el('change-new-password').value
                })
            });
            const data = await res.json();
            if (!res.ok) {
                changePasswordMessage.textContent = data.error || 'Fehler beim Ändern des Passworts';
                changePasswordMessage.style.color = 'var(--danger-color)';
                show(changePasswordMessage);
            } else {
                changePasswordMessage.textContent = data.message;
                changePasswordMessage.style.color = 'var(--success-color)';
                show(changePasswordMessage);
                changePasswordForm.reset();
            }
        } catch(err) {
            changePasswordMessage.textContent = 'Netzwerkfehler';
            changePasswordMessage.style.color = 'var(--danger-color)';
            show(changePasswordMessage);
        }
    });
}

if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorEl = el('login-error');
        hide(errorEl);
        
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    email: el('login-email').value,
                    password: el('login-password').value
                })
            });
            const data = await res.json();
            if (!res.ok) {
                errorEl.textContent = data.error || 'Login failed';
                show(errorEl);
            } else {
                loginForm.reset();
                checkAuth();
            }
        } catch(err) {
            errorEl.textContent = 'Network error';
            show(errorEl);
        }
    });
}

if (registerForm) {
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const errorEl = el('register-error');
        const successEl = el('register-success');
        hide(errorEl);
        hide(successEl);
        
        try {
            const res = await fetch('/api/auth/register', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken()
                },
                body: JSON.stringify({
                    first_name: el('register-first').value,
                    last_name: el('register-last').value,
                    email: el('register-email').value,
                    password: el('register-password').value
                })
            });
            const data = await res.json();
            if (!res.ok) {
                errorEl.textContent = data.error || 'Registration failed';
                show(errorEl);
            } else {
                registerForm.reset();
                successEl.textContent = data.message + " (Check terminal for mock verification link)";
                show(successEl);
            }
        } catch(err) {
            errorEl.textContent = 'Network error';
            show(errorEl);
        }
    });
}

if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
        try {
            await fetch('/api/auth/logout', { 
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            checkAuth();
        } catch(err) {
            console.error(err);
        }
    });
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
});
'''

start_marker = '// Form logic'

import sys
start_idx = content.find(start_marker)
if start_idx == -1:
    print('Start marker not found')
    sys.exit(1)

new_content = content[:start_idx] + replacement

with open('static/script.js', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Successfully patched script.js')
