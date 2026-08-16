# -*- coding: utf-8 -*-
import sys

new_code = '''// Form logic
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

const showDeleteAccountBtn = el('show-delete-account-btn');
const cancelDeleteAccountBtn = el('cancel-delete-account-btn');
const deleteAccountConfirmation = el('delete-account-confirmation');
const deleteAccountForm = el('delete-account-form');
const deleteAccountMessage = el('delete-account-message');

async function safeAuthFetch(url, options) {
    if (options && ['POST', 'PUT', 'PATCH', 'DELETE'].includes((options.method || 'GET').toUpperCase())) {
        options.headers = { ...options.headers, 'X-CSRFToken': getCsrfToken() };
    }
    let response;
    try {
        response = await fetch(url, options);
    } catch (err) {
        throw new Error('Network error');
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        const data = await response.json();
        return { ok: response.ok, status: response.status, data };
    } else {
        return { ok: response.ok, status: response.status, data: { error: HTTP  + response.status +  (Serverfehler) } };
    }
}

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
        if (deleteAccountConfirmation) hide(deleteAccountConfirmation);
        if (deleteAccountMessage) hide(deleteAccountMessage);
        
        if (data.authenticated) {
            show(loggedInView);
            el('profile-name').textContent = data.user.first_name + " " + data.user.last_name;
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
                // Clean URL
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
            const res = await safeAuthFetch('/api/auth/forgot-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: el('forgot-email').value })
            });
            forgotMessage.textContent = res.data.message || 'Link gesendet.';
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
            const res = await safeAuthFetch('/api/auth/reset-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    token: resetTokenInput.value,
                    new_password: el('reset-new-password').value
                })
            });
            if (!res.ok) {
                resetMessage.textContent = res.data.error || 'Fehler beim Zurücksetzen';
                resetMessage.style.color = 'var(--danger-color)';
                show(resetMessage);
            } else {
                resetMessage.textContent = res.data.message;
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
            const res = await safeAuthFetch('/api/auth/resend-verification', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: el('profile-email') ? el('profile-email').textContent : ''
                })
            });
            resendMessage.textContent = res.data.message || 'Bestätigungslink gesendet.';
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
            const res = await safeAuthFetch('/api/auth/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: el('change-current-password').value,
                    new_password: el('change-new-password').value
                })
            });
            if (!res.ok) {
                changePasswordMessage.textContent = res.data.error || 'Fehler beim Ändern';
                changePasswordMessage.style.color = 'var(--danger-color)';
                show(changePasswordMessage);
            } else {
                changePasswordMessage.textContent = res.data.message;
                changePasswordMessage.style.color = 'var(--success-color)';
                show(changePasswordMessage);
                changePasswordForm.reset();
                // We reload on success because this changes sessions_valid_after 
                // which invalidates the current session.
                setTimeout(() => {
                    window.location.reload();
                }, 1500);
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
            const res = await safeAuthFetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: el('login-email').value,
                    password: el('login-password').value
                })
            });
            if (!res.ok) {
                errorEl.textContent = res.data.error || 'Login failed';
                show(errorEl);
            } else {
                loginForm.reset();
                window.location.reload();
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
            const res = await safeAuthFetch('/api/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    first_name: el('register-first').value,
                    last_name: el('register-last').value,
                    email: el('register-email').value,
                    password: el('register-password').value
                })
            });
            if (!res.ok) {
                errorEl.textContent = res.data.error || 'Registration failed';
                show(errorEl);
            } else {
                registerForm.reset();
                successEl.textContent = res.data.message;
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
            await safeAuthFetch('/api/auth/logout', { 
                method: 'POST'
            });
            window.location.reload();
        } catch(err) {
            console.error(err);
        }
    });
}

if (showDeleteAccountBtn) {
    showDeleteAccountBtn.addEventListener('click', () => {
        show(deleteAccountConfirmation);
    });
}

if (cancelDeleteAccountBtn) {
    cancelDeleteAccountBtn.addEventListener('click', () => {
        hide(deleteAccountConfirmation);
        if (deleteAccountForm) deleteAccountForm.reset();
        if (deleteAccountMessage) hide(deleteAccountMessage);
    });
}

if (deleteAccountForm) {
    deleteAccountForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        hide(deleteAccountMessage);
        
        try {
            const res = await safeAuthFetch('/api/auth/delete-account', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: el('delete-current-password').value
                })
            });
            if (!res.ok) {
                deleteAccountMessage.textContent = res.data.error || 'Fehler beim Löschen';
                deleteAccountMessage.style.color = 'var(--danger-color)';
                show(deleteAccountMessage);
            } else {
                deleteAccountForm.reset();
                window.location.reload();
            }
        } catch(err) {
            deleteAccountMessage.textContent = 'Netzwerkfehler';
            deleteAccountMessage.style.color = 'var(--danger-color)';
            show(deleteAccountMessage);
        }
    });
}

'''

with open('static/script.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if '// Form logic' in line:
        start_idx = i
    if '// Init' in line:
        end_idx = i

if start_idx == -1 or end_idx == -1:
    print("Could not find blocks")
    sys.exit(1)

# we need to append newline to the replacement code
lines[start_idx:end_idx] = [new_code + '\n']

with open('static/script.js', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Patched script.js")
