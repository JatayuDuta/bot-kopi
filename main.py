import telebot
import gspread
import os
import pytz
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
import json

# === TOKEN BOT TELEGRAM & ADMIN ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(TOKEN)

# === AMANKAN CREDENTIALS GOOGLE ===
with open("google_credentials.json", "w") as f:
    f.write(os.getenv("GOOGLE_CREDS"))

creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# === Akses Spreadsheet dan Sheet ===
sheet = client.open("Penjualan_Kopi_Harian")
menu_sheet = sheet.worksheet("DATA_MENU")
transaksi_sheet = sheet.worksheet("TRANSAKSI")
rekap_sheet = sheet.worksheet("REKAP_HARIAN")

# === Ambil menu dari sheet ===
def get_menu_data():
    return menu_sheet.get_all_records()

# === Start Bot ===
@bot.message_handler(commands=["start"])
def start(message):
    menus = get_menu_data()
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    for m in menus:
        markup.add(m["Menu"])
    msg = bot.send_message(message.chat.id, "☕ Hai! Silakan pilih menu kopi:", reply_markup=markup)
    bot.register_next_step_handler(msg, proses_menu)

# === Proses Menu ===
def proses_menu(message):
    menu = message.text
    menus = get_menu_data()
    for m in menus:
        if m["Menu"] == menu:
            harga = m["Harga_Jual"]
            hpp = m["HPP"]
            msg = bot.send_message(message.chat.id, f"Berapa cup {menu}?")
            bot.register_next_step_handler(msg, lambda msg: simpan_transaksi(msg, menu, harga, hpp))
            return
    bot.send_message(message.chat.id, "❌ Menu tidak ditemukan.")

# === Simpan Transaksi ===
def simpan_transaksi(message, menu, harga, hpp):
    try:
        jumlah = int(message.text)
        zona_wib = pytz.timezone('Asia/Jakarta')
        waktu = datetime.now(zona_wib).strftime('%H:%M:%S')
        tanggal = datetime.today().strftime("%Y-%m-%d")

        total = jumlah * harga
        laba = jumlah * (harga - hpp)

        # Tambah ke TRANSAKSI
        transaksi_sheet.append_row([tanggal, waktu, menu, jumlah, harga, hpp, total, laba])

        # Update stok
        stok_data = menu_sheet.get_all_records()
        for i, row in enumerate(stok_data):
            if row["Menu"] == menu:
                stok_sekarang = row["Stok_Awal"] - jumlah
                menu_sheet.update_acell(f"D{i+2}", stok_sekarang)
                if stok_sekarang <= 5:
                    bot.send_message(ADMIN_ID, f"⚠️ Stok {menu} tinggal {stok_sekarang} cup!")
                break

        # Rekap harian (jumlahkan dari semua transaksi hari ini)
        transaksi_data = transaksi_sheet.get_all_records()
        total_hari_ini = sum([t["Total"] for t in transaksi_data if t["Tanggal"] == tanggal])
        laba_hari_ini = sum([t["Laba"] for t in transaksi_data if t["Tanggal"] == tanggal])

        rekap_data = rekap_sheet.get_all_records()
        tanggal_list = [r["Tanggal"] for r in rekap_data]

        if tanggal in tanggal_list:
            row_idx = tanggal_list.index(tanggal) + 2
            rekap_sheet.update_acell(f"B{row_idx}", total_hari_ini)
            rekap_sheet.update_acell(f"C{row_idx}", laba_hari_ini)
        else:
            rekap_sheet.append_row([tanggal, total_hari_ini, laba_hari_ini])

        # Balasan ke user
        bot.send_message(message.chat.id, f"✅ Transaksi dicatat!\nMenu: {menu}\nJumlah: {jumlah}\nTotal: Rp{total}\nLaba: Rp{laba}")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Terjadi kesalahan:\n{e}")

# === Mulai Polling ===
bot.polling()
