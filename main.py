import os, threading, json
from pathlib import Path

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.image import Image as KivyImage
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import platform
from kivy.storage.jsonstore import JsonStore

from food import analyze_image, format_results

Window.softinput_mode = "below_target"

STORE_PATH = os.path.join(os.path.expanduser("~"), ".openfood.json") if platform != "android" else "openfood.json"

class FoodApp(App):
    def build(self):
        self.title = "OpenFood - Calorias con foto"
        self.store = JsonStore(STORE_PATH)
        self.selected_image = None
        self.api_key = self.store.get("config")["api_key"] if self.store.exists("config") else ""

        root = BoxLayout(orientation="vertical", padding=12, spacing=10)

        root.add_widget(Label(text="[b]OpenFood[/b]\nHaz una foto y calcula calorias", markup=True, size_hint_y=None, height=50, font_size=18))

        self.api_input = TextInput(
            hint_text="GEMINI_API_KEY (aistudio.google.com/apikey)",
            text=self.api_key,
            password=True,
            multiline=False,
            size_hint_y=None,
            height=44,
        )
        self.api_input.bind(text=self.on_api_key)
        root.add_widget(self.api_input)

        btn_row = BoxLayout(size_hint_y=None, height=50, spacing=8)
        self.btn_gallery = Button(text="Galeria", background_color=(0.2,0.6,0.86,1))
        self.btn_camera = Button(text="Camara", background_color=(0.2,0.8,0.4,1))
        self.btn_gallery.bind(on_release=self.pick_gallery)
        self.btn_camera.bind(on_release=self.take_photo)
        btn_row.add_widget(self.btn_gallery)
        btn_row.add_widget(self.btn_camera)
        root.add_widget(btn_row)

        self.preview = KivyImage(source="", size_hint_y=None, height=260, allow_stretch=True, keep_ratio=True)
        root.add_widget(self.preview)

        self.btn_analyze = Button(text="ANALIZAR COMIDA", size_hint_y=None, height=55, background_color=(1,0.45,0.2,1), disabled=True)
        self.btn_analyze.bind(on_release=self.do_analyze)
        root.add_widget(self.btn_analyze)

        self.status = Label(text="Elige una foto para empezar", size_hint_y=None, height=30, color=(0.6,0.6,0.6,1))
        root.add_widget(self.status)

        scroll = ScrollView()
        self.result_box = GridLayout(cols=1, size_hint_y=None, spacing=6, padding=8)
        self.result_box.bind(minimum_height=self.result_box.setter("height"))
        self.result_label = Label(text="", markup=True, size_hint_y=None, halign="left", valign="top")
        self.result_label.bind(texture_size=self._update_label_height)
        self.result_label.bind(width=lambda *x: self.result_label.setter("text_size")(self.result_label, (self.result_label.width, None)))
        self.result_box.add_widget(self.result_label)
        scroll.add_widget(self.result_box)
        root.add_widget(scroll)

        return root

    def _update_label_height(self, inst, size):
        inst.height = size[1]
        inst.text_size = (inst.width, None)

    def on_api_key(self, inst, val):
        self.api_key = val.strip()
        self.store.put("config", api_key=self.api_key)
        self._refresh_analyze_btn()

    def _refresh_analyze_btn(self):
        self.btn_analyze.disabled = not (self.selected_image and self.api_key)

    def pick_gallery(self, *a):
        try:
            from plyer import filechooser
            filechooser.open_file(on_selection=self.on_file_selected, filters=[("Images", "*.jpg", "*.jpeg", "*.png")])
        except Exception as e:
            self.set_status(f"Error galeria: {e}", error=True)
            try:
                from android.storage import primary_external_storage_path
                self.set_status("Usa el gestor de archivos", error=True)
            except: pass

    def on_file_selected(self, sel):
        if sel:
            self.set_image(sel[0])

    def take_photo(self, *a):
        try:
            from plyer import camera
            tmp = os.path.join(self.user_data_dir, "capture.jpg") if hasattr(self, "user_data_dir") else "/tmp/capture.jpg"
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            camera.take_picture(filename=tmp, on_complete=self.on_camera_done)
        except Exception as e:
            self.set_status(f"Error camara: {e}. Usa Galeria", error=True)

    def on_camera_done(self, path):
        if path and os.path.exists(path):
            Clock.schedule_once(lambda dt: self.set_image(path))

    def set_image(self, path):
        self.selected_image = path
        self.preview.source = path
        self.preview.reload()
        self.set_status(f"Foto: {os.path.basename(path)}")
        self._refresh_analyze_btn()
        self.result_label.text = ""

    def set_status(self, msg, error=False):
        Clock.schedule_once(lambda dt: setattr(self.status, "text", msg))
        Clock.schedule_once(lambda dt: setattr(self.status, "color", (1,0.3,0.3,1) if error else (0.2,0.6,0.2,1)))

    def do_analyze(self, *a):
        if not self.selected_image or not self.api_key:
            self.set_status("Falta foto o API key", error=True)
            return
        self.btn_analyze.disabled = True
        self.btn_analyze.text = "ANALIZANDO..."
        self.set_status("Enviando a Gemini...")
        self.result_label.text = "[i]Analizando, espera...[/i]"
        threading.Thread(target=self._analyze_thread, daemon=True).start()

    def _analyze_thread(self):
        try:
            data = analyze_image(self.selected_image, self.api_key)
            text = format_results(data)
            pretty = self._format_pretty(data, text)
            Clock.schedule_once(lambda dt: self.show_result(pretty, data))
        except Exception as e:
            err = str(e)[:600]
            Clock.schedule_once(lambda dt: self.show_error(err))

    def _format_pretty(self, data, plain):
        cal = data.get("calories", 0)
        p = data.get("protein", 0)
        c = data.get("carbs", 0)
        f = data.get("fat", 0)
        g = data.get("serving_size_grams", 0)
        name = data.get("name", "Comida")
        ings = data.get("ingredients", [])

        out = f"[b][size=18]{name}[/size][/b]\n"
        out += f"[color=888888]~{g:.0f}g  |  [b][color=ff6b35]{cal} kcal[/color][/b][/color]\n"
        out += f"[b]P:[/b] {p:.1f}g  [b]C:[/b] {c:.1f}g  [b]G:[/b] {f:.1f}g\n"
        out += "[color=cccccc]────────────────[/color]\n"
        if ings:
            for it in ings:
                out += f"\n[b]{it.get('name','?')}[/b] [color=888888]~{it.get('grams',0):.0f}g[/color]\n"
                out += f"  [color=ff6b35]{it.get('calories',0)} kcal[/color]  P:{it.get('protein',0):.1f} C:{it.get('carbs',0):.1f} G:{it.get('fat',0):.1f}\n"
            out += "\n[color=cccccc]────────────────[/color]\n"
        out += f"\n[b][size=16]TOTAL: {cal} kcal[/size][/b]\n"
        out += f"P {p:.1f}g  C {c:.1f}g  G {f:.1f}g"
        return out

    def show_result(self, pretty, data):
        self.result_label.text = pretty
        self.btn_analyze.text = "ANALIZAR COMIDA"
        self.btn_analyze.disabled = False
        self.set_status("Listo!")

    def show_error(self, err):
        self.result_label.text = f"[color=ff3333][b]Error:[/b]\n{err}[/color]"
        self.btn_analyze.text = "ANALIZAR COMIDA"
        self.btn_analyze.disabled = False
        self.set_status("Error", error=True)

if __name__ == "__main__":
    FoodApp().run()
