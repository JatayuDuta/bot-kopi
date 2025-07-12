import telebot
import gspread
import os
import pytz
import json
import threading
import time
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# === Ambil token dan ID admin dari environment variable ===
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = telebot.TeleBot(TOKEN)

# === Setup Google Sheets credentials dari ENV ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_dict = json.loads(os.getenv("GOOGLE_CREDS"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# === Akses sheet ===
sheet = client.open("Penjualan_Kopi_Harian")
menu_sheet = sheet.worksheet("DATA_MENU")
transaksi_sheet = sheet.worksheet("TRANSAKSI")
rekap_sheet = sheet.worksheet("REKAP_HARIAN")

# === Ambil data menu ===
def get_menu_data():
    return menu_sheet.get_all_records()

# === Update sisa stok secara real time ke REKAP_HARIAN ===
def update_sisa_stok_ke_rekap():
    zona_wib = pytz.timezone('Asia/Jakarta')
    hari_ini = datetime.now(zona_wib).strftime('%Y-%m-%d')

    stok_data = menu_sheet.get_all_records()
    sisa_stok_dict = {}
    total_sisa = 0

    for row in stok_data:
        sisa_stok_dict[row["Menu"]] = row["Stok_Awal"]
        total_sisa += row["Stok_Awal"]

    detail_sisa = "\n".join([f"{menu}: {stok}" for menu, stok in sisa_stok_dict.items()])

    rekap_data = rekap_sheet.get_all_records()
    tanggal_list = [r["Tanggal"] for r in rekap_data]

    if hari_ini in tanggal_list:
        row_idx = tanggal_list.index(hari_ini) + 2
        rekap_sheet.update_acell(f"D{row_idx}", detail_sisa)
        rekap_sheet.update_acell(f"E{row_idx}", total_sisa)
    else:
        rekap_sheet.append_row([hari_ini, 0, 0, detail_sisa, total_sisa])

# === Reset stok harian otomatis ===
def reset_stok_harian():
    zona_wib = pytz.timezone('Asia/Jakarta')
    hari_ini = datetime.now(zona_wib).strftime('%Y-%m-%d')

    stok_data = menu_sheet.get_all_records()
    sisa_stok_dict = {}
    total_sisa = 0

    for i, row in enumerate(stok_data):
        sisa_stok = row["Stok_Awal"]
        sisa_stok_dict[row["Menu"]] = sisa_stok
        total_sisa += sisa_stok
        menu_sheet.update_acell(f"D{i+2}", 100)  # Reset ke 100

    detail_sisa = "\n".join([f"{menu}: {stok}" for menu, stok in sisa_stok_dict.items()])
    rekap_data = rekap_sheet.get_all_records()
    tanggal_list = [r["Tanggal"] for r in rekap_data]

    if hari_ini in tanggal_list:
        row_idx = tanggal_list.index(hari_ini) + 2
        rekap_sheet.update_acell(f"D{row_idx}", detail_sisa)
        rekap_sheet.update_acell(f"E{row_idx}", total_sisa)
    else:
        rekap_sheet.append_row([hari_ini, 0, 0, detail_sisa, total_sisa])

# === Jalankan reset stok jam 00:00 WIB setiap hari ===
def jadwal_reset_stok():
    while True:
        zona_wib = pytz.timezone('Asia/Jakarta')
        sekarang = datetime.now(zona_wib)
        if sekarang.hour == 0 and sekarang.minute == 0:
            reset_stok_harian()
            time.sleep(60)
        time.sleep(30)

threading.Thread(target=jadwal_reset_stok, daemon=True).start()

# === Mulai Bot ===
@bot.message_handler(commands=["start"])
def start(message):
    menus = get_menu_data()
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    for m in menus:
        markup.add(m["Menu"])
    msg = bot.send_message(message.chat.id, "☕ Hai! Silakan pilih menu kopi:", reply_markup=markup)
    bot.register_next_step_handler(msg, proses_menu)

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

def simpan_transaksi(message, menu, harga, hpp):
    try:
        jumlah = int(message.text)
        zona_wib = pytz.timezone('Asia/Jakarta')
        waktu = datetime.now(zona_wib).strftime('%H:%M:%S')
        tanggal = datetime.now(zona_wib).strftime("%Y-%m-%d")

        total = jumlah * harga
        laba = jumlah * (harga - hpp)

        transaksi_sheet.append_row([tanggal, waktu, menu, jumlah, harga, hpp, total, laba])

        stok_data = menu_sheet.get_all_records()
        for i, row in enumerate(stok_data):
            if row["Menu"] == menu:
                stok_sekarang = row["Stok_Awal"] - jumlah
                menu_sheet.update_acell(f"D{i+2}", stok_sekarang)
                if stok_sekarang <= 5:
                    bot.send_message(ADMIN_ID, f"⚠️ Stok {menu} tinggal {stok_sekarang} cup!")
                break

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

        update_sisa_stok_ke_rekap()

        bot.send_message(message.chat.id, f"✅ Transaksi dicatat!\nMenu: {menu}\nJumlah: {jumlah}\nTotal: Rp{total}\nLaba: Rp{laba}")

    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Terjadi kesalahan:\n{e}")

# === Jalankan Bot ===
bot.polling()
