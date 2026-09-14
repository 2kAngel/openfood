# Plan de Integración de Modelo de Clasificación Local (Offline) en OpenFood

Este documento detalla el diseño de arquitectura y el plan técnico para migrar o expandir la aplicación **OpenFood** con soporte de análisis de comida **100% offline y local**, eliminando la dependencia obligatoria de una API key externa (como la de Gemini).

---

## 1. Arquitectura de Diseño: Enfoque Dual (Recomendado)

Para ofrecer la mejor experiencia de usuario posible, proponemos una arquitectura de **Modo Dual**:

1. **Modo Online (Gemini AI)**: Mantiene la funcionalidad actual. Utiliza Gemini 1.5 Flash / Flash-Lite para analizar platos complejos (múltiples ingredientes, porciones personalizadas) con alta precisión. Requiere API Key y conexión a internet.
2. **Modo Offline (Modelo Local)**: Utiliza un modelo **TensorFlow Lite (TFLite)** embebido directamente en el APK, junto con una base de datos nutricional local (`food_db.json`). No requiere API Key ni conexión a internet.

---

## 2. Componentes Técnicos del Modo Offline

### A. El Modelo Clasificador: MobileNetV2 / EfficientNet-Lite
Utilizaremos un clasificador pre-entrenado en el dataset de comida **Food-101** (101 categorías de platos populares).
- **Formato**: TensorFlow Lite (`.tflite`), cuantizado (INT8) para un rendimiento ultrarrápido en CPU móvil y menor tamaño de archivo.
- **Tamaño del modelo**: ~13 MB (MobileNetV2) o ~28 MB (EfficientNet-Lite0).
- **Entrada**: Imagen de `224x224x3` (o `299x299x3`).
- **Salida**: Vector de 101 flotantes que representan las probabilidades para cada clase.

### B. Base de Datos Nutricional Local (`food_db.json`)
Dado que el modelo local solo clasifica la imagen en una de las 101 categorías (por ejemplo, `pizza`, `salad`, `spaghetti_bolognese`), necesitamos un mapa local para devolver información nutricional realista por porción estándar de 100g o por ración completa.

Ejemplo del formato de `food_db.json`:
```json
{
  "pizza": {
    "name": "Pizza",
    "calories": 266,
    "protein": 11.0,
    "carbs": 33.0,
    "fat": 10.0,
    "serving_size_grams": 250,
    "ingredients": [
      {"name": "Masa de pizza", "grams": 150, "calories": 400, "protein": 11.2, "carbs": 75.0, "fat": 3.0},
      {"name": "Queso Mozzarella", "grams": 60, "calories": 180, "protein": 13.0, "carbs": 1.5, "fat": 14.0},
      {"name": "Salsa de tomate", "grams": 40, "calories": 20, "protein": 0.8, "carbs": 4.0, "fat": 0.2}
    ]
  },
  "caesar_salad": {
    "name": "Ensalada César",
    "calories": 127,
    "protein": 3.0,
    "carbs": 5.0,
    "fat": 11.0,
    "serving_size_grams": 200,
    "ingredients": []
  }
}
```

---

## 3. Integración en Kivy y Android (Desafío de Compilación superado)

### El problema tradicional con Python en Android
Compilar `tensorflow` o `tflite-runtime` para Android usando `python-for-android` (p4a) es sumamente complejo y suele fallar debido a incompatibilidades de compiladores cruzados C/C++ (NDK).

### La Solución Elegante: Usar el SDK Nativo de Android con Pyjnius
En lugar de compilar la biblioteca de Python, **usaremos la biblioteca nativa oficial de TensorFlow Lite para Android a través de Pyjnius**. Esto es 100% estable, rápido de compilar, y aprovecha la aceleración por hardware (GPU/NNAPI) si está disponible en el dispositivo móvil.

1. **Gradle Dependencies**: Añadimos las dependencias de Google al proceso de compilación nativa en `buildozer.spec`:
   ```ini
   android.gradle_dependencies = org.tensorflow:tensorflow-lite:2.12.0, org.tensorflow:tensorflow-lite-support:0.4.3
   ```

2. **Carga directa del Modelo**: Los archivos `.tflite` y `food_db.json` se empaquetan dentro de los assets del APK. En tiempo de ejecución, se extraen a la carpeta local de la app, permitiéndonos leerlos directamente:
   ```python
   # Android path
   model_path = os.path.join(os.path.dirname(__file__), "model.tflite")
   ```

3. **Inferencia Nativa vía Pyjnius**:
   Usaremos `android.graphics.BitmapFactory` para decodificar la imagen a un Bitmap nativo de Android, y luego `TensorImage` de la suite de soporte de TFLite para procesarla e inyectarla en el intérprete sin necesidad de manipular bytes crudos en Python lento.

---

## 4. Borrador del Código Técnico de Inferencia

### Archivo sugerido: `local_model.py`

```python
import os, json
from kivy.utils import platform

class LocalFoodClassifier:
    def __init__(self, model_filename="model.tflite", labels_filename="labels.txt", db_filename="food_db.json"):
        self.model_path = os.path.join(os.path.dirname(__file__), model_filename)
        self.labels_path = os.path.join(os.path.dirname(__file__), labels_filename)
        self.db_path = os.path.join(os.path.dirname(__file__), db_filename)
        
        # Cargar etiquetas
        with open(self.labels_path, "r", encoding="utf-8") as f:
            self.labels = [line.strip() for line in f.readlines()]
            
        # Cargar base de datos nutricional
        with open(self.db_path, "r", encoding="utf-8") as f:
            self.food_db = json.load(f)
            
        self.is_android = (platform == "android")
        self.interpreter = None
        
        if self.is_android:
            self._init_android_tflite()
        else:
            print("Ejecutando en Escritorio (Modo simulación / tflite-runtime si está disponible)")

    def _init_android_tflite(self):
        from jnius import autoclass
        File = autoclass('java.io.File')
        Interpreter = autoclass('org.tensorflow.lite.Interpreter')
        
        model_file = File(self.model_path)
        # Inicializa el intérprete de C++ nativo de Android
        self.interpreter = Interpreter(model_file)

    def classify_image(self, img_path: str) -> dict:
        """Clasifica la imagen y devuelve los macros correspondientes."""
        if not self.is_android:
            # Fallback en escritorio para desarrollo: simular predicción
            import random
            class_name = random.choice(self.labels)
            return self._get_nutrition_for_class(class_name, confidence=0.85)
            
        # Código nativo Android
        from jnius import autoclass, FloatArray
        BitmapFactory = autoclass('android.graphics.BitmapFactory')
        TensorImage = autoclass('org.tensorflow.lite.support.image.TensorImage')
        DataType = autoclass('org.tensorflow.lite.DataType')
        
        # 1. Cargar imagen en Bitmap nativo
        bitmap = BitmapFactory.decodeFile(img_path)
        
        # 2. Convertir a TensorImage de TFLite
        tensor_image = TensorImage(DataType.UINT8) # o FLOAT32 dependiendo del modelo
        tensor_image.load(bitmap)
        
        # 3. Preparar buffer de salida (101 clases de probabilidades)
        output_buffer = FloatArray(len(self.labels))
        # Ajustamos el formato para pasar un array bidimensional float[1][101]
        import numpy as np # Si no usamos numpy, usamos arrays nativos de Pyjnius
        
        # Ejecutar inferencia
        # java: interpreter.run(tensor_image.getBuffer(), output_buffer)
        self.interpreter.run(tensor_image.getBuffer().rewind(), output_buffer)
        
        # 4. Encontrar la clase con mayor probabilidad
        max_idx = 0
        max_val = -1.0
        for i in range(len(output_buffer)):
            if output_buffer[i] > max_val:
                max_val = output_buffer[i]
                max_idx = i
                
        best_class = self.labels[max_idx]
        return self._get_nutrition_for_class(best_class, confidence=max_val)

    def _get_nutrition_for_class(self, class_name: str, confidence: float) -> dict:
        """Busca la clase en la DB local y genera la estructura JSON requerida por la app."""
        info = self.food_db.get(class_name, {
            "name": class_name.replace("_", " ").title(),
            "calories": 150,
            "protein": 5.0,
            "carbs": 15.0,
            "fat": 5.0,
            "serving_size_grams": 100,
            "ingredients": []
        })
        
        # Creamos una estructura idéntica a la respuesta de Gemini para no romper la UI
        return {
            "name": f"{info['name']} (Local, conf: {confidence*100:.1f}%)",
            "calories": info["calories"],
            "protein": info["protein"],
            "carbs": info["carbs"],
            "fat": info["fat"],
            "serving_size_grams": info["serving_size_grams"],
            "ingredients": info.get("ingredients", [])
        }
```

---

## 5. Cambios en la Interfaz Gráfica (`main.py`)

Para integrar esto de forma transparente e intuitiva para el usuario:

1. **Selector de Modo (Switch / Segmented Control)**:
   - Añadir un control horizontal (ToggleButtons) en la parte superior:
     `[ Modo Offline (Local) ]  [ Modo Online (Gemini AI) ]`
2. **Visibilidad dinámica de la API Key**:
   - Si el Modo Offline está seleccionado, el `TextInput` de la API Key se oculta o se deshabilita con un mensaje explicativo ("No requerido en modo offline").
   - Si se selecciona Modo Online, se muestra el campo.
3. **Botón Analizar**:
   - En Modo Offline, el botón "ANALIZAR COMIDA" se habilitará **siempre** que haya una foto seleccionada, sin importar si hay API Key.

---

## 6. Plan de Ejecución Paso a Paso

1. **Obtención del Modelo**: Descargar un modelo `food101_quant.tflite` de alta calidad (como el de TensorFlow Hub o HuggingFace) y su archivo `labels.txt`.
2. **Generación de la Base de Datos**: Crear un archivo `food_db.json` que traduzca las 101 etiquetas en inglés al español y asocie valores nutricionales realistas para cada plato.
3. **Modificación de `buildozer.spec`**:
   - Agregar las dependencias gradle de TensorFlow Lite.
   - Asegurar que `.tflite`, `.txt` y `.json` estén en los archivos incluidos para el empaque.
4. **Crear `local_model.py`** con la lógica de inferencia Pyjnius nativa.
5. **Actualizar `food.py`**:
   - Exponer un método común unificado: `analyze_image(img_path, api_key=None, mode="online")`.
   - Si `mode == "offline"`, delega a `LocalFoodClassifier`.
6. **Actualizar `main.py`**:
   - Implementar el ToggleButton de selección de modo.
   - Ajustar el flujo del hilo de análisis para pasar el parámetro `mode`.
7. **Verificación en CI (GitHub Actions)**:
   - Subir cambios y verificar que GitHub Actions compile el APK con las nuevas dependencias gradle sin inconvenientes.
   - Probar la instalación del APK en un dispositivo Android real.
