source venv/bin/activate
psql -U user_hr_bot -h localhost -d hr_bot_db

sudo systemctl start tg_bot_Vkusvill.service

journalctl -u tg_bot_Vkusvill.service -f