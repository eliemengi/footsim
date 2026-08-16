# -*- coding: utf-8 -*-
import json
import os

de_file = os.path.join('static', 'i18n', 'de.json')
with open(de_file, 'r', encoding='utf-8') as f:
    de_data = json.load(f)

de_data.update({
  "account.profile": "Profil",
  "account.security": "Sicherheit",
  "account.account": "Account",
  "account.emailNotVerified": "Email nicht bestätigt.",
  "account.resendLink": "Bestätigungslink erneut senden",
  "account.changePasswordBtn": "Passwort ändern",
  "account.logout": "Logout",
  "account.deleteAccount": "Account löschen",
  "account.deleteWarning": "Achtung: Dies kann nicht rückgängig gemacht werden.",
  "account.confirmDelete": "Endgültig löschen",
  "account.cancel": "Abbrechen"
})

with open(de_file, 'w', encoding='utf-8') as f:
    json.dump(de_data, f, ensure_ascii=False, indent=2)

en_file = os.path.join('static', 'i18n', 'en.json')
with open(en_file, 'r', encoding='utf-8') as f:
    en_data = json.load(f)

en_data.update({
  "account.profile": "Profile",
  "account.security": "Security",
  "account.account": "Account",
  "account.emailNotVerified": "Email not verified.",
  "account.resendLink": "Resend verification link",
  "account.changePasswordBtn": "Change password",
  "account.logout": "Logout",
  "account.deleteAccount": "Delete account",
  "account.deleteWarning": "Warning: This cannot be undone.",
  "account.confirmDelete": "Permanently delete",
  "account.cancel": "Cancel"
})

with open(en_file, 'w', encoding='utf-8') as f:
    json.dump(en_data, f, ensure_ascii=False, indent=2)
