-- Secondo database di test (sorgente V1 nei test di integrazione): vive solo nel container temporaneo.
CREATE DATABASE gestione_consegne_src_test CHARACTER SET utf8mb4;
GRANT ALL PRIVILEGES ON gestione_consegne_src_test.* TO 'test'@'%';
