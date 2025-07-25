#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_height_gui_asl.py (拡張版)
---------------------------------
KMZ 内の WPML 高度をオフセット付きで変換し、
relativeToStartPoint → EGM96 に置換。
・ウェイポイントでの写真撮影をオプション化
・撮影オフ時のみジンバル制御のオン／オフ選択可能
・撮影オン時はジンバル制御も実行
依存ライブラリ:
pip install lxml tkinterdnd2
"""

import os
import shutil
import zipfile
import glob
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from tkinterdnd2 import TkinterDnD, DND_FILES
from lxml import etree

# WPML 名前空間
NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "wpml": "http://www.dji.com/wpmz/1.0.6"
}

# GUI 用：基準高度選択リスト
HEIGHT_OPTIONS = {
    "613.5 – 事務所前": 613.5,
    "962.02 – 烏帽子": 962.02,
    "その他 – 手動入力": "custom"
}

def extract_kmz(kmz_path: str, work_dir: str) -> None:
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(work_dir)
    with zipfile.ZipFile(kmz_path, "r") as zf:
        zf.extractall(work_dir)

def prepare_output_dirs(input_kmz: str, offset: float) -> (str, str):
    base_name = os.path.splitext(os.path.basename(input_kmz))[0]
    sign = "+" if offset >= 0 else "-"
    out_base = f"{base_name}_asl{sign}{abs(offset)}"
    input_dir = os.path.dirname(input_kmz)
    base_out_dir = os.path.join(input_dir, out_base)
    if os.path.exists(base_out_dir):
        shutil.rmtree(base_out_dir)
    os.makedirs(base_out_dir)
    wpmz_dir = os.path.join(base_out_dir, "wpmz")
    os.makedirs(wpmz_dir)
    return base_out_dir, wpmz_dir

def repackage_to_kmz(base_out_dir: str, input_kmz: str) -> str:
    input_dir = os.path.dirname(input_kmz)
    kmz_name = f"{os.path.splitext(os.path.basename(input_kmz))[0]}_Converted.kmz"
    out_kmz = os.path.join(input_dir, kmz_name)
    tmp_zip = out_kmz + ".zip"
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base_out_dir):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, base_out_dir)
                zf.write(full, rel)
    if os.path.exists(out_kmz):
        os.remove(out_kmz)
    os.rename(tmp_zip, out_kmz)
    return out_kmz

def convert_heights_and_mode(tree: etree._ElementTree, offset: float,
                             do_capture: bool, do_gimbal: bool) -> None:
    # 高度オフセットと heightMode の変更
    for pm in tree.findall(".//kml:Placemark", NS):
        for tag in ("height", "ellipsoidHeight"):
            elem = pm.find(f"wpml:{tag}", NS)
            if elem is not None:
                try:
                    elem.text = str(float(elem.text) + offset)
                except:
                    pass
    gh = tree.find(".//wpml:globalHeight", NS)
    if gh is not None:
        try:
            gh.text = str(float(gh.text) + offset)
        except:
            pass
    for hm in tree.findall(".//wpml:heightMode", NS):
        hm.text = "EGM96"

    # 撮影指令 orientedShoot の処理
    for ag in tree.findall(".//wpml:actionGroup", NS):
        for action in ag.findall("wpml:action", NS):
            func = action.find("wpml:actionActuatorFunc", NS)
            if func is not None and func.text == "orientedShoot":
                param = action.find("wpml:actionActuatorFuncParam", NS)
                # 撮影オフなら、このアクションを削除
                if not do_capture:
                    # gimbalRotate を保持 or 削除
                    if do_gimbal and param is not None:
                        new_act = etree.SubElement(ag, "{http://www.dji.com/wpmz/1.0.6}action")
                        etree.SubElement(new_act, "{http://www.dji.com/wpmz/1.0.6}actionId").text = "0"
                        etree.SubElement(new_act, "{http://www.dji.com/wpmz/1.0.6}actionActuatorFunc").text = "gimbalRotate"
                        new_param = etree.SubElement(new_act, "{http://www.dji.com/wpmz/1.0.6}actionActuatorFuncParam")
                        pitch = param.find("wpml:gimbalPitchRotateAngle", NS)
                        if pitch is not None:
                            etree.SubElement(new_param, "{http://www.dji.com/wpmz/1.0.6}gimbalPitchRotateAngle").text = pitch.text
                        yaw = param.find("wpml:gimbalYawRotateAngle", NS)
                        if yaw is not None:
                            etree.SubElement(new_param, "{http://www.dji.com/wpmz/1.0.6}gimbalYawRotateAngle").text = yaw.text
                    ag.remove(action)
                # 撮影オンなら、元のまま（ジンバル含む）保持
    # 空の actionGroup は除去
    for ag in tree.findall(".//wpml:actionGroup", NS):
        if len(ag.findall("wpml:action", NS)) == 0:
            parent = ag.getparent()
            parent.remove(ag)

def process_kmz(input_kmz: str, offset: float,
                do_capture: bool, do_gimbal: bool, log: tk.Text) -> None:
    work_dir = "_kmz_work"
    try:
        log.insert(tk.END, f"Extracting {os.path.basename(input_kmz)}...\n")
        extract_kmz(input_kmz, work_dir)
        kml_files = glob.glob(os.path.join(work_dir, "**", "template.kml"), recursive=True)
        if not kml_files:
            raise FileNotFoundError("template.kml が見つかりません")
        base_out_dir, wpmz_dir = prepare_output_dirs(input_kmz, offset)
        for kml in kml_files:
            log.insert(tk.END, f"Converting {os.path.basename(kml)}...\n")
            tree = etree.parse(kml)
            convert_heights_and_mode(tree, offset, do_capture, do_gimbal)
            out_kml = os.path.join(wpmz_dir, os.path.basename(kml))
            tree.write(out_kml, encoding="utf-8", pretty_print=True, xml_declaration=True)
        # resとwaylines.wpml をコピー
        for src in glob.glob(os.path.join(work_dir, "**", "res"), recursive=True):
            dst = os.path.join(wpmz_dir, "res")
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log.insert(tk.END, "Copied res folder\n")
        for src in glob.glob(os.path.join(work_dir, "**", "waylines.wpml"), recursive=True):
            dst = os.path.join(wpmz_dir, "waylines.wpml")
            shutil.copy2(src, dst)
            log.insert(tk.END, "Copied waylines.wpml\n")
        out_kmz = repackage_to_kmz(base_out_dir, input_kmz)
        log.insert(tk.END, f"Saved: {out_kmz}\nFinished\n\n")
        messagebox.showinfo("完了", f"変換完了:\n{out_kmz}")
    except Exception as e:
        messagebox.showerror("エラー", str(e))
        log.insert(tk.END, f"Error: {e}\n\n")
    finally:
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir)

# --- GUI 構築 ---
class HeightSelector(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        # 基準高度オフセット
        ttk.Label(self, text="基準高度オフセット:").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(self, values=list(HEIGHT_OPTIONS.keys()),
                                  state="readonly", width=20)
        self.combo.set(next(iter(HEIGHT_OPTIONS)))
        self.combo.grid(row=0, column=1, padx=5)
        self.entry = ttk.Entry(self, width=10, state="disabled")
        self.entry.grid(row=0, column=2, padx=5)
        self.combo.bind("<<ComboboxSelected>>", self.on_select)
        # 撮影オプション
        self.capture_var = tk.BooleanVar(value=False)
        self.capture_chk = ttk.Checkbutton(self, text="ウェイポイントで写真撮影を行う",
                                           variable=self.capture_var,
                                           command=self.update_gimbal_state)
        self.capture_chk.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5,0))
        # ジンバルオプション（初期disabled）
        self.gimbal_var = tk.BooleanVar(value=True)
        self.gimbal_chk = ttk.Checkbutton(self, text="ジンバル操作を保持する",
                                          variable=self.gimbal_var)
        self.gimbal_chk.grid(row=2, column=0, columnspan=3, sticky="w", pady=(5,0))
        self.update_gimbal_state()

    def on_select(self, _=None):
        choice = self.combo.get()
        if HEIGHT_OPTIONS[choice] == "custom":
            self.entry.config(state="normal")
            self.entry.delete(0, tk.END)
            self.entry.focus()
        else:
            self.entry.config(state="disabled")
            self.entry.delete(0, tk.END)

    def update_gimbal_state(self):
        # 撮影オフ時のみジンバルチェックを有効化
        if self.capture_var.get():
            self.gimbal_chk.state(['disabled'])
            self.gimbal_var.set(True)  # 撮影オン時は自動で保持
        else:
            self.gimbal_chk.state(['!disabled'])

    def get_offset(self) -> float:
        choice = self.combo.get()
        val = HEIGHT_OPTIONS[choice]
        if val == "custom":
            try:
                return float(self.entry.get())
            except:
                return 0.0
        return float(val)

    def get_capture_option(self) -> bool:
        return self.capture_var.get()

    def get_gimbal_option(self) -> bool:
        return self.gimbal_var.get()

def main():
    root = TkinterDnD.Tk()
    root.title("ATL → ASL 高度変換＆ジンバル制御ツール")
    root.geometry("660x450")

    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    # コントロールパネル
    height_selector = HeightSelector(frame)
    height_selector.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,10))

    # ドラッグ＆ドロップ
    drop_lbl = tk.Label(frame, text="ここに .kmz をドラッグ＆ドロップ",
                        bg="lightgray", width=60, height=5, relief=tk.RIDGE)
    drop_lbl.grid(row=1, column=0, columnspan=2, pady=12, sticky="nsew")
    drop_lbl.drop_target_register(DND_FILES)

    def on_drop(event):
        path = event.data.strip("{}")
        if not path.lower().endswith(".kmz"):
            messagebox.showwarning("警告", "KMZファイルのみ対応")
            return
        offset = height_selector.get_offset()
        do_capture = height_selector.get_capture_option()
        do_gimbal = height_selector.get_gimbal_option()
        threading.Thread(target=process_kmz,
                         args=(path, offset, do_capture, do_gimbal, log_text),
                         daemon=True).start()

    drop_lbl.dnd_bind("<<Drop>>", on_drop)

    # ログ表示
    log_frame = ttk.LabelFrame(frame, text="ログ")
    log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew")
    frame.rowconfigure(2, weight=1)
    frame.columnconfigure(1, weight=1)
    log_text = scrolledtext.ScrolledText(log_frame, height=14, state="normal")
    log_text.pack(fill="both", expand=True)

    root.mainloop()

if __name__ == "__main__":
    main()
