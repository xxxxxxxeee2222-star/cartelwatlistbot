# cartelwt

Telegram whitelist bot without hub.

Commands:
- `/add <nick>` add a nick to whitelist
- `/nicks` show your nicks

Admin commands:
- `/stats` show total nicks and recent additions
- `/who <nick>` show who added a nick

Admin access is controlled by `admin_ids` in `bot/config.json`.

The bot writes:
- `bot/users.json` for user nick lists
- `bot/audit.json` for add history
