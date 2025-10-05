source venv/bin/activate
psql -U user_hr_bot -h localhost -d hr_bot_db

sudo systemctl start tg_bot_Vkusvill.service

journalctl -u tg_bot_Vkusvill.service -f


Для основного воркера (сделать все по порядку после тестирования для установки сервиса)
sudo systemctl daemon-reload
sudo systemctl start hh_bot_worker
sudo systemctl status hh_bot_worker
sudo journalctl -u hh_bot_worker -f
sudo systemctl stop hh_bot_worker
sudo systemctl enable hh_bot_worker



curl -X POST "https://api.hh.ru/token" \
-H "Content-Type: application/x-www-form-urlencoded" \
-d "grant_type=refresh_token" \
-d "client_id=LTCF16K8FHJMP7CIIS2MQH1JU4AGDE8OU90NQV17CV5A3G1R6QQJOTHVCAS25BU4" \
-d "client_secret=LRLEARAPRUTS3QG56AD5CA8O94E12CLLNNSGI1U8N27LEGNGI9JTEODK4SG5Q7QP" \
-d "refresh_token=USERTTGRQG4BKDRL1K3S7IL02DHRUPAL91JEBA659HTG2HBLCEJ6A7702JH5IGU0"