from typing import List, Dict, Optional, Tuple, Callable
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import os
import time
from .database import TranslationDatabase
from .translator import TranslatorLogic

class TranslationWorker(QObject):
    progress_updated = pyqtSignal(str)
    translation_completed = pyqtSignal(str, bool)
    all_translations_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, files_to_translate: List[Dict[str, str]],
                 working_directory: str, db: TranslationDatabase,
                 translator: TranslatorLogic, source_lang: str,
                 target_lang: str, api_key: str, provider: str,
                 model: str, custom_terms: str = "",
                 segment_size: Optional[int] = None):
        super().__init__()
        self.files_to_translate = files_to_translate
        self.working_directory = working_directory
        self.db = db
        self.translator = translator
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.api_key = api_key
        self.provider = provider
        self.model = model
        self.custom_terms = custom_terms
        self.segment_size = segment_size
        self._stop_requested = False
        self.translator.segment_size = segment_size

    def stop(self):
        self._stop_requested = True

    def run(self):
        try:
            total_files = len(self.files_to_translate)
            successful_translations = 0

            # Configurar tamaño de segmento si se especificó
            if self.segment_size is not None:
                        self.translator.segment_size = self.segment_size

            for i, file_info in enumerate(self.files_to_translate, 1):
                if self._stop_requested:
                    break

                filename = file_info['name']
                self.progress_updated.emit(f"Traduciendo capítulo {i} de {total_files}: {filename}")

                # Verificar si ya está traducido
                if self.db.is_file_translated(filename):
                    continue

                # Traducir el archivo
                success = self._translate_single_file(filename)

                if success:
                    successful_translations += 1
                    self.db.add_translation_record(filename, self.source_lang, self.target_lang)
                    self.translation_completed.emit(filename, True)
                else:
                    self.translation_completed.emit(filename, False)

                # Esperar antes de la siguiente traducción si no es el último archivo
                if i < total_files and not self._stop_requested:
                    time.sleep(5)

            if not self._stop_requested:
                final_message = (f"Traducción completada. {successful_translations} "
                               f"de {total_files} archivos traducidos exitosamente.")
                self.progress_updated.emit(final_message)
                self.all_translations_completed.emit()

        except Exception as e:
            self.error_occurred.emit(f"Error en el proceso de traducción: {str(e)}")
        finally:
            self.all_translations_completed.emit()

    def _translate_single_file(self, filename: str) -> bool:
        try:
            input_path = os.path.join(self.working_directory, filename)
            temp_output_path = os.path.join(self.working_directory, f".temp_{filename}")

            # Leer archivo original
            with open(input_path, 'r', encoding='utf-8') as file:
                text = file.read()

            # Intentar traducir
            translated_text = self.translator.translate_text(
                text,
                self.source_lang,
                self.target_lang,
                self.api_key,
                self.provider,
                self.model,
                self.custom_terms
            )

            if not translated_text:
                self.error_occurred.emit(f"Error al traducir {filename}: No se obtuvo traducción")
                return False

            # Guardar primero en archivo temporal
            with open(temp_output_path, 'w', encoding='utf-8') as file:
                file.write(translated_text)

            # Si todo salió bien, reemplazar el archivo original
            os.replace(temp_output_path, input_path)
            return True

        except Exception as e:
            self.error_occurred.emit(f"Error al traducir {filename}: {str(e)}")
            # Limpiar archivo temporal si existe
            if os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except:
                    pass
            return False

class TranslationManager(QObject):
    # Señales para comunicar con la UI
    progress_updated = pyqtSignal(str)
    translation_completed = pyqtSignal(str, bool)
    all_translations_completed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.translator = TranslatorLogic(segment_size=None)
        self.db: Optional[TranslationDatabase] = None
        self.working_directory: Optional[str] = None
        self.current_provider = None
        self.current_model = None
        self.worker = None
        self.thread = None

    def initialize(self, directory: str, provider: str = None, model: str = None) -> None:
        """
        Inicializa el administrador de traducción con un directorio de trabajo.

        Args:
            directory: Ruta al directorio de trabajo
            provider: Proveedor de traducción
            model: Modelo de traducción
        """
        self.working_directory = directory
        self.db = TranslationDatabase(directory)
        self.current_provider = provider
        self.current_model = model

    def translate_files(self, files_to_translate: List[Dict[str, str]],
                       source_lang: str, target_lang: str, api_key: str,
                       status_callback: Optional[Callable[[str, str], None]] = None,
                       custom_terms: str = "", segment_size: Optional[int] = None) -> None:
        """
        Inicia la traducción de archivos.

        Args:
            files_to_translate: Lista de diccionarios con información de archivos
            source_lang: Idioma de origen
            target_lang: Idioma de destino
            api_key: API key del servicio
            status_callback: Función para actualizar el estado en la UI
            custom_terms: Términos personalizados para la traducción
            segment_size: Tamaño de segmentación opcional (caracteres por segmento)
        """
        if not self.working_directory or not self.db:
            self.error_occurred.emit("No se ha inicializado el directorio de trabajo")
            return

        # Guardar términos personalizados
        if custom_terms.strip():
            self.db.save_custom_terms(custom_terms)

        # Crear y configurar el worker
        self.thread = QThread()
        self.worker = TranslationWorker(
            files_to_translate,
            self.working_directory,
            self.db,
            self.translator,
            source_lang,
            target_lang,
            api_key,
            self.current_provider,
            self.current_model,
            custom_terms,
            segment_size
        )

        # Mover el worker al thread
        self.worker.moveToThread(self.thread)

        # Conectar señales
        self.thread.started.connect(self.worker.run)
        self.worker.progress_updated.connect(self.progress_updated)
        self.worker.translation_completed.connect(self.translation_completed)
        self.worker.all_translations_completed.connect(self.all_translations_completed)
        self.worker.error_occurred.connect(self.error_occurred)

        # Conectar el callback de estado si existe
        if status_callback:
            self.worker.translation_completed.connect(
                lambda filename, success: status_callback(filename, "Traducido" if success else "Error")
            )

        # Limpieza cuando termine
        self.worker.all_translations_completed.connect(self.thread.quit)
        self.worker.all_translations_completed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # Iniciar el thread
        self.thread.start()

    def stop_translation(self) -> None:
        """Detiene el proceso de traducción en curso"""
        if self.worker:
            self.worker.stop()
            self.progress_updated.emit("Deteniendo traducción...")

    def get_supported_languages(self) -> Dict[str, str]:
        """Obtiene la lista de idiomas soportados"""
        return self.translator.get_supported_languages()

    def get_custom_terms(self) -> str:
        """Obtiene los términos personalizados guardados"""
        if self.db:
            return self.db.get_custom_terms()
        return ""
