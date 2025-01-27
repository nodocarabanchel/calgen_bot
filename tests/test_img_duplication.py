import os
import logging
from pathlib import Path

# Ajusta estos imports a tu estructura real:
# from src.utils import DuplicateDetector, load_config
from src.utils import DuplicateDetector, load_config

# Configurar un logger simple para el script
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
    """
    detector = DuplicateDetector(config)

    # Diccionario para almacenar los hashes de las imágenes (ruta -> hash_dict)
    processed_hashes = {}
    # Lista de rutas de imágenes procesadas
    processed_files = []

    # Resultados para luego imprimir
    results = []
    image_paths = sorted(Path(image_folder).glob("*.*"))  # Cambia el patrón si lo prefieres

    for img_path in image_paths:
        logger.info(f"Analizando imagen: {img_path.name}")

        # 1) Calculamos SIEMPRE el hash de la imagen actual
        current_hashes = detector.calculate_image_hash(img_path)
        if not current_hashes:
            logger.warning(f"No se pudo calcular hash para {img_path.name}")
            results.append((img_path.name, False, None))
            continue

        # 2) Comparamos con todas las imágenes ya procesadas (sin 'return' inmediato)
        found_duplicate_of = None
        for pf in processed_files:
            stored_hash = processed_hashes.get(str(pf))
            if not stored_hash:
                # En caso de que no esté calculado, lo calculamos aquí.
                stored_hash = detector.calculate_image_hash(pf)
                processed_hashes[str(pf)] = stored_hash

            # Primero comparamos hashes
            similar, distance = detector.compare_hashes(current_hashes, stored_hash)
            if similar:
                # Luego análisis por regiones
                differences = detector.analyze_image_regions(img_path, pf)
                logger.debug(f"{img_path.name} vs {pf.name}: {len(differences)} regiones sobre umbral.")
                if len(differences) <= detector.min_differences:
                    # Marcamos el primer duplicado que encontremos
                    found_duplicate_of = pf
                    # IMPORTANTE: no rompemos el bucle si quieres ver si coincide con más de uno
                    # Pero si solo nos interesa el primer duplicado, podemos hacer break
                    break

        # 3) Añadimos SIEMPRE su hash a processed_hashes y su ruta a processed_files
        #    (incluso si es duplicada) para que futuras imágenes puedan compararse con ella.
        processed_hashes[str(img_path)] = current_hashes
        processed_files.append(img_path)

        # 4) Guardamos el resultado
        if found_duplicate_of:
            logger.info(f"--> {img_path.name} SE DETECTÓ como duplicado de {found_duplicate_of.name}")
            results.append((img_path.name, True, found_duplicate_of.name))
        else:
            logger.info(f"--> {img_path.name} NO se detectó como duplicado.")
            results.append((img_path.name, False, None))

    return results

if __name__ == "__main__":
    # Cargar la configuración (que contiene duplicate_detection, etc.)
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
