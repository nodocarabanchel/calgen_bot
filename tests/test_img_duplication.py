import os
import logging
from pathlib import Path

# from src.utils import DuplicateDetector, load_config
from src.utils import DuplicateDetector, load_config

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def test_duplicate_detection(image_folder, config):
    """
    Ejecuta un test que compara cada imagen con todas las ya procesadas,
    de modo que podamos ver si el cálculo de hashes y regiones detecta
    duplicados, independientemente de la lógica de 'no procesar duplicadas'
    que se use en producción.

    Returns:
        list: Lista de tuplas (nombre_imagen, es_duplicado: bool, duplicado_de: str|None)
    """
    detector = DuplicateDetector(config)

    processed_hashes = {}
    processed_files = []
    results = []

    image_paths = sorted(Path(image_folder).glob("*.*"))

    for img_path in image_paths:
        logger.info(f"Analizando imagen: {img_path.name}")

        # Calcular hash de la imagen actual
        current_hashes = detector.calculate_image_hash(img_path)
        if not current_hashes:
            logger.warning(f"No se pudo calcular hash para {img_path.name}")
            results.append((img_path.name, False, None))
            continue

        found_duplicate_of = None
        # Comparar con las imágenes ya procesadas
        for pf in processed_files:
            stored_hash = processed_hashes.get(str(pf))
            if not stored_hash:
                stored_hash = detector.calculate_image_hash(pf)
                processed_hashes[str(pf)] = stored_hash

            # Comparar hashes
            similar, distance = detector.compare_hashes(current_hashes, stored_hash)
            if similar:
                # Luego análisis por regiones
                differences = detector.analyze_image_regions(img_path, pf)
                logger.debug(
                    f"{img_path.name} vs {pf.name}: {len(differences)} regiones sobre umbral."
                )
                if len(differences) <= detector.min_differences:
                    found_duplicate_of = pf
                    break

        # Agregar la imagen actual a la lista y dict de hashes
        processed_hashes[str(img_path)] = current_hashes
        processed_files.append(img_path)

        # Guardar resultado en la lista
        if found_duplicate_of:
            logger.info(
                f"--> {img_path.name} SE DETECTÓ como duplicado de {found_duplicate_of.name}"
            )
            results.append((img_path.name, True, found_duplicate_of.name))
        else:
            logger.info(f"--> {img_path.name} NO se detectó como duplicado.")
            results.append((img_path.name, False, None))

    return results

if __name__ == "__main__":
    # Cargar la configuración
    config = load_config()
    print("Configuración de duplicate_detection usada:", config["duplicate_detection"])

    # Ruta a la carpeta con las imágenes de prueba
    test_folder = "tests/test_images"

    # Ejecutar test
    results = test_duplicate_detection(test_folder, config)

    print("\n===== RESULTADOS DEL TEST DE DUPLICADOS =====")
    for item in results:
        nombre_imagen, es_duplicate, duplicado_de = item
        if es_duplicate and duplicado_de:
            print(f"[DUPLICADO] {nombre_imagen} -> duplicado de {duplicado_de}")
        else:
            print(f"[UNICO]     {nombre_imagen}")

    # == Estadísticas adicionales ==
    total_imagenes = len(results)
    # Filtramos cuántas resultaron duplicadas
    duplicados = [r for r in results if r[1] == True]
    num_duplicados = len(duplicados)
    num_unicas = total_imagenes - num_duplicados

    print("\n===== ESTADÍSTICAS =====")
    print(f"Número total de imágenes analizadas: {total_imagenes}")
    print(f"Número de duplicados detectados: {num_duplicados}")
    print(f"Número de imágenes únicas: {num_unicas}")
