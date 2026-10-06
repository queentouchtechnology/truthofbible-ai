# Server Script access fixes (apply in the Frappe desk)

These Server Scripts live in the database, not in this app, so they are not
changed by `bench migrate`. Apply each by pasting `patched/<name>.py` into
**Server Script → `<name>` → Script** and saving. `original/` holds the exact
previous version for rollback.

Every patch adds an "access guard" block only — the rest of each script is
unchanged. Calls made as `Administrator` (every app build that still uses the
shared admin key) behave exactly as before, so applying these does not break
the current app. Any other caller is limited to their own data or blocked
unless they hold an admin role.

| Script | Problem fixed |
|---|---|
| Approve Withdrawal / Reject Withdrawal | No role check — any signed-in user could approve their own wallet withdrawal (journal entry posted with ignore_permissions). Now System Manager / Accounts Manager only. |
| Reward Quiz Users | No role check — any user could mint reward coupons. Now LMS admin roles only. |
| Quiz answer sheet | Any user could read every member's answers. Now LMS admin roles only. |
| Save FCM token | Took a `user` parameter — anyone could redirect another user's push notifications to their own phone. Now always the caller. |
| Get customer wallet balance | Any user could read any customer's wallet. Now own customer only (admins: any). |
| Get Quiz User Status | Any user could read another student's quiz status. Now own only. |
| Submit Withdrawal | Could submit someone else's request. Now own requests only. |
| Get Full Issue | Any user could read any support ticket thread. Now own tickets only (support/admin roles: any). |
| Quiz Compare1 | Any user could view any submission with the correct answers. Now own submissions only. |

Also do in the desk:

- **Disable `Custom Email`** (`send-mail`): it is guest-allowed and sends any
  email to any address — an open mail relay on this domain. The app does not
  use it.
- **`Send OTP New`** returns the OTP in its response and builds it from the
  clock. The new app uses `truth_of_bible.api.app_auth.send_otp` instead;
  disable the script once old app builds are retired (after the forced
  update + admin-key rotation).
- The new `app_auth.send_otp` sends WhatsApp codes through Chatwoot (its
  site_config credentials) and drops SMS. Once `Send OTP New` is disabled,
  rotate the Meta WhatsApp token and the SMS key still written inside that
  script: anyone holding the leaked Administrator key could read Server
  Scripts.
