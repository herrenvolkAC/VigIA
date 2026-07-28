import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

public class OracleProductividadQuery {
    private static final DateTimeFormatter TS_FMT =
        DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss").withZone(ZoneId.systemDefault());
    private static final String ALMACEN_DIVISION_SQL =
        "CASE " +
        "WHEN SUB1.DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA' " +
        "WHEN SUB1.DESCDIVI = 'CAMARA 06' THEN 'CAMARA 06' " +
        "WHEN SUB1.DESCDIVI LIKE 'CAMARA%' THEN 'OTRAS CAMARAS' " +
        "ELSE SUB1.DESCDIVI END";
    private static final String ALMACEN_GRUPO_SQL =
        "CASE " +
        "WHEN F.DESCRIPCION IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS', 'SECOS + NOA ', 'SECOS + NOA') THEN 'SECOS + NOA' " +
        "WHEN F.DESCRIPCION = 'CAMARA 06' THEN 'CAMARA 06' " +
        "WHEN F.DESCRIPCION LIKE 'CAMARA%' THEN 'OTRAS CAMARAS' " +
        "ELSE F.DESCRIPCION END";

    private static String esc(String value) {
        if (value == null) return "";
        return value
            .replace("\\", "\\\\")
            .replace("\"", "\\\"")
            .replace("\r", "\\r")
            .replace("\n", "\\n");
    }

    private static String str(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static String num(Object value) {
        if (value == null) return "0";
        if (value instanceof Number) return value.toString();
        try {
            return Double.toString(Double.parseDouble(String.valueOf(value)));
        } catch (Exception e) {
            return "0";
        }
    }

    private static boolean hasColumn(ResultSet rs, String column) {
        try {
            rs.findColumn(column);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private static String[] splitList(String value) {
        if (value == null || value.trim().isEmpty()) return new String[] {"__SIN_LEGAJOS__"};
        return value.split("\\s*,\\s*");
    }

    private static String placeholders(String value) {
        String[] items = splitList(value);
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < items.length; i++) {
            if (i > 0) out.append(",");
            out.append("?");
        }
        return out.toString();
    }

    private static void appendGenericJsonRow(ResultSet rs, StringBuilder out) throws Exception {
        var meta = rs.getMetaData();
        int columns = meta.getColumnCount();
        out.append("{");
        for (int i = 1; i <= columns; i++) {
            if (i > 1) out.append(",");
            String name = meta.getColumnLabel(i);
            Object value = rs.getObject(i);
            out.append("\"").append(esc(name)).append("\":");
            if (value == null) {
                out.append("null");
            } else if (value instanceof Number) {
                out.append(num(value));
            } else if (value instanceof Timestamp) {
                out.append("\"").append(esc(TS_FMT.format(((Timestamp) value).toInstant()))).append("\"");
            } else {
                out.append("\"").append(esc(str(value))).append("\"");
            }
        }
        out.append("}");
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.err.println("Uso: OracleProductividadQuery <jdbcUrl> <user> <password> <fechaDesde> <fechaHasta> [queryKey]");
            System.exit(2);
        }

        String jdbcUrl = args[0];
        String user = args[1];
        String password = args[2];
        String fechaDesde = args[3];
        String fechaHasta = args[4];
        String queryKey = args.length >= 6 ? args[5] : "productividad";
        String legajo = args.length >= 7 ? args[6] : "";
        String operacionArg = args.length >= 8 ? args[7] : "PICKING";
        String nivelArg = args.length >= 9 ? args[8] : "";
        String grupoFuncionesArg = args.length >= 10 ? args[9] : "1";
        String fechaOperativaArg = args.length >= 11 ? args[10] : "";
        String legajoDetalleArg = args.length >= 12 ? args[11] : legajo;
        String almacenArg = args.length >= 13 ? args[12] : "SECOS + NOA";

        String sql;
        if ("monitor_cargas".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH VIAJES AS (
                    SELECT
                        V.CEMPRESA,
                        V.CCENTDIS,
                        V.CNUVIAJE,
                        V.HOJARUTA,
                        V.CAMIMATR,
                        V.CNUANDEN,
                        V.CDIVISIO,
                        V.CARGADOR,
                        V.FCREAREG,
                        V.FEAPERTU,
                        V.FMODIREG,
                        V.CSITVIAJ,
                        T.QPALMAXI,
                        T.QVOLMAXI
                    FROM F810VIAJ V
                    LEFT JOIN F811TRAI T
                      ON T.CEMPRESA = V.CEMPRESA
                     AND T.CAMIMATR = V.CAMIMATR
                    WHERE V.CSITVIAJ = 'EP'
                ),
                EXPEDICIONES AS (
                    SELECT
                        V.CEMPRESA,
                        V.CCENTDIS,
                        V.CNUVIAJE,
                        E.CNUMEXPE,
                        E.CSITEXPE,
                        E.FCREACIO,
                        E.QTBULTOS AS BULTOS_F035,
                        E.QVOLTOTA AS VOLUMEN_F035
                    FROM VIAJES V
                    JOIN F035EXPE E
                      ON E.CEMPRESA = V.CEMPRESA
                     AND E.CCENTDIS = V.CCENTDIS
                     AND E.CNUVIAJE = V.CNUVIAJE
                ),
                PALLETS AS (
                    SELECT
                        E.CEMPRESA,
                        E.CCENTDIS,
                        E.CNUVIAJE,
                        E.CNUMEXPE,
                        P.CALMACEN,
                        P.CNUPALET,
                        P.QTBULTOS,
                        P.QVOLTOTA,
                        P.CSITPALS,
                        P.CTIPTRAB,
                        P.CTIPPALS
                    FROM EXPEDICIONES E
                    JOIN F080CPSA P
                      ON P.CEMPRESA = E.CEMPRESA
                     AND P.CNUMEXPE = E.CNUMEXPE
                    WHERE NVL(P.XANULADA, 'N') <> 'S'
                ),
                LINEAS_ACTIVAS AS (
                    SELECT
                        P.CEMPRESA,
                        P.CCENTDIS,
                        P.CNUVIAJE,
                        P.CNUMEXPE,
                        P.CALMACEN,
                        P.CNUPALET,
                        L.CREFEPLA,
                        L.CVARLPLA,
                        L.CCNSGPRO,
                        L.QCANTIDA
                    FROM PALLETS P
                    JOIN F081LPSA L
                      ON L.CEMPRESA = P.CEMPRESA
                     AND L.CALMACEN = P.CALMACEN
                     AND L.CNUPALET = P.CNUPALET
                ),
                CLAVES_VLOG AS (
                    SELECT DISTINCT
                        CEMPRESA,
                        CCNSGPRO,
                        CREFEPLA,
                        CVARLPLA
                    FROM LINEAS_ACTIVAS
                ),
                VLOG AS (
                    SELECT
                        G.CEMPRESA,
                        G.CCONSIGN,
                        G.CREFEREN,
                        G.CVARLOGI,
                        MAX(G.CCNIVELE) AS CCNIVELE,
                        MAX(G.QCANTDEP) AS QCANTDEP,
                        MAX(G.NALTUEXP) AS NALTUEXP,
                        MAX(G.NANCHEXP) AS NANCHEXP,
                        MAX(G.NLONGEXP) AS NLONGEXP,
                        COUNT(*) AS COINCIDENCIAS
                    FROM F054VLOG G
                    JOIN CLAVES_VLOG K
                      ON K.CEMPRESA = G.CEMPRESA
                     AND K.CCNSGPRO = G.CCONSIGN
                     AND K.CREFEPLA = G.CREFEREN
                     AND K.CVARLPLA = G.CVARLOGI
                    GROUP BY
                        G.CEMPRESA,
                        G.CCONSIGN,
                        G.CREFEREN,
                        G.CVARLOGI
                ),
                LINEAS_PALLET AS (
                    SELECT
                        L.CEMPRESA,
                        L.CNUVIAJE,
                        L.CNUMEXPE,
                        L.CALMACEN,
                        L.CNUPALET,
                        COUNT(*) AS LINEAS,
                        SUM(
                            CASE G.CCNIVELE
                                WHEN 2 THEN L.QCANTIDA
                                WHEN 3 THEN L.QCANTIDA * G.QCANTDEP
                                ELSE 0
                            END
                        ) AS BULTOS_CALCULADOS,
                        SUM(
                            CASE
                                WHEN G.NALTUEXP > 0
                                 AND G.NANCHEXP > 0
                                 AND G.NLONGEXP > 0
                                THEN L.QCANTIDA * G.NALTUEXP * G.NANCHEXP * G.NLONGEXP / 1000
                                ELSE 0
                            END
                        ) AS VOLUMEN_CALCULADO,
                        SUM(
                            CASE
                                WHEN NVL(L.QCANTIDA, 0) > 0
                                 AND G.CREFEREN IS NULL
                                THEN 1 ELSE 0
                            END
                        ) AS LINEAS_SIN_VLOG,
                        SUM(
                            CASE
                                WHEN NVL(L.QCANTIDA, 0) > 0
                                 AND (
                                     NVL(G.NALTUEXP, 0) <= 0
                                     OR NVL(G.NANCHEXP, 0) <= 0
                                     OR NVL(G.NLONGEXP, 0) <= 0
                                 )
                                THEN 1 ELSE 0
                            END
                        ) AS LINEAS_SIN_DIMENSION,
                        SUM(
                            CASE
                                WHEN NVL(L.QCANTIDA, 0) > 0
                                 AND NVL(G.CCNIVELE, -1) NOT IN (2, 3)
                                THEN 1 ELSE 0
                            END
                        ) AS LINEAS_NIVEL_INVALIDO,
                        SUM(
                            CASE
                                WHEN NVL(L.QCANTIDA, 0) > 0
                                 AND NVL(G.COINCIDENCIAS, 0) > 1
                                THEN 1 ELSE 0
                            END
                        ) AS LINEAS_VLOG_DUPLICADA
                    FROM LINEAS_ACTIVAS L
                    LEFT JOIN VLOG G
                      ON G.CEMPRESA = L.CEMPRESA
                     AND G.CCONSIGN = L.CCNSGPRO
                     AND G.CREFEREN = L.CREFEPLA
                     AND G.CVARLOGI = L.CVARLPLA
                    GROUP BY
                        L.CEMPRESA,
                        L.CNUVIAJE,
                        L.CNUMEXPE,
                        L.CALMACEN,
                        L.CNUPALET
                ),
                CARGA_EXPEDICION AS (
                    SELECT
                        P.CEMPRESA,
                        P.CNUVIAJE,
                        P.CNUMEXPE,
                        COUNT(*) AS PALLETS,
                        SUM(NVL(L.LINEAS, 0)) AS LINEAS,
                        SUM(NVL(L.BULTOS_CALCULADOS, 0)) AS BULTOS_CALCULADOS,
                        SUM(NVL(L.VOLUMEN_CALCULADO, 0)) AS VOLUMEN_CALCULADO,
                        SUM(P.QTBULTOS) AS BULTOS_F080,
                        SUM(P.QVOLTOTA) AS VOLUMEN_F080,
                        SUM(
                            CASE
                                WHEN L.CNUPALET IS NULL
                                 AND (NVL(P.QTBULTOS, 0) > 0 OR NVL(P.QVOLTOTA, 0) > 0)
                                THEN 1 ELSE 0
                            END
                        ) AS PALLETS_SIN_DETALLE,
                        SUM(NVL(L.LINEAS_SIN_VLOG, 0)) AS LINEAS_SIN_VLOG,
                        SUM(NVL(L.LINEAS_SIN_DIMENSION, 0)) AS LINEAS_SIN_DIMENSION,
                        SUM(NVL(L.LINEAS_NIVEL_INVALIDO, 0)) AS LINEAS_NIVEL_INVALIDO,
                        SUM(NVL(L.LINEAS_VLOG_DUPLICADA, 0)) AS LINEAS_VLOG_DUPLICADA
                    FROM PALLETS P
                    LEFT JOIN LINEAS_PALLET L
                      ON L.CEMPRESA = P.CEMPRESA
                     AND L.CNUVIAJE = P.CNUVIAJE
                     AND L.CNUMEXPE = P.CNUMEXPE
                     AND L.CALMACEN = P.CALMACEN
                     AND L.CNUPALET = P.CNUPALET
                    GROUP BY
                        P.CEMPRESA,
                        P.CNUVIAJE,
                        P.CNUMEXPE
                )
                SELECT
                    V.CEMPRESA,
                    V.CCENTDIS,
                    V.CNUVIAJE,
                    V.HOJARUTA,
                    V.CAMIMATR,
                    V.CNUANDEN,
                    V.CDIVISIO,
                    CASE
                        WHEN V.CDIVISIO IN (1, 3) THEN 'SECOS'
                        WHEN V.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                        WHEN V.CDIVISIO = 6 THEN 'NOA'
                        ELSE 'OTROS'
                    END AS DIVISION,
                    V.CARGADOR,
                    V.FCREAREG,
                    V.FEAPERTU,
                    V.FMODIREG,
                    V.QPALMAXI,
                    V.QVOLMAXI,
                    E.CNUMEXPE,
                    E.CSITEXPE,
                    E.FCREACIO AS FECHA_EXPEDICION,
                    NVL(C.PALLETS, 0) AS PALLETS,
                    NVL(C.LINEAS, 0) AS LINEAS,
                    NVL(C.BULTOS_CALCULADOS, 0) AS BULTOS_CALCULADOS,
                    ROUND(NVL(C.VOLUMEN_CALCULADO, 0), 3) AS VOLUMEN_CALCULADO,
                    NVL(C.BULTOS_F080, 0) AS BULTOS_F080,
                    ROUND(NVL(C.VOLUMEN_F080, 0), 3) AS VOLUMEN_F080,
                    NVL(E.BULTOS_F035, 0) AS BULTOS_F035,
                    ROUND(NVL(E.VOLUMEN_F035, 0), 3) AS VOLUMEN_F035,
                    NVL(C.PALLETS_SIN_DETALLE, 0) AS PALLETS_SIN_DETALLE,
                    NVL(C.LINEAS_SIN_VLOG, 0) AS LINEAS_SIN_VLOG,
                    NVL(C.LINEAS_SIN_DIMENSION, 0) AS LINEAS_SIN_DIMENSION,
                    NVL(C.LINEAS_NIVEL_INVALIDO, 0) AS LINEAS_NIVEL_INVALIDO,
                    NVL(C.LINEAS_VLOG_DUPLICADA, 0) AS LINEAS_VLOG_DUPLICADA,
                    SYSDATE AS ORACLE_NOW
                FROM VIAJES V
                LEFT JOIN EXPEDICIONES E
                  ON E.CEMPRESA = V.CEMPRESA
                 AND E.CCENTDIS = V.CCENTDIS
                 AND E.CNUVIAJE = V.CNUVIAJE
                LEFT JOIN CARGA_EXPEDICION C
                  ON C.CEMPRESA = E.CEMPRESA
                 AND C.CNUVIAJE = E.CNUVIAJE
                 AND C.CNUMEXPE = E.CNUMEXPE
                ORDER BY
                    CASE WHEN V.CNUANDEN IS NULL THEN 1 ELSE 0 END,
                    V.CNUANDEN,
                    NVL(V.FEAPERTU, V.FCREAREG) DESC,
                    E.CNUMEXPE
                """;
        } else if ("rend_premio_dias_pago".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    FECHA,
                    LEGAJO
                FROM PV_DIA_LABORAL
                WHERE FECHA >= TO_NUMBER(REPLACE(?, '-', ''))
                  AND FECHA <= TO_NUMBER(REPLACE(?, '-', ''))
                ORDER BY FECHA, LEGAJO
                """;
        } else if ("rend_premio_escalas".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    B.DESCRIPCION AS OPERACION,
                    C.DESCRIPCION AS DIVISION,
                    A.NIVEL,
                    A.DESDE,
                    A.HASTA,
                    A.PREMIO
                FROM PV_ESCALA_DE_PREMIOS A
                JOIN PV_GRUPO_DE_FUNCIONES_CAB B ON A.ID_DE_GRUPO_DE_FUNCIONES = B.ID
                JOIN PV_GRUPO_PRODUCTIVO_CAB C ON A.ID_DE_GRUPO_PRODUCTIVO = C.ID
                WHERE B.DESCRIPCION = 'PICKING'
                ORDER BY C.DESCRIPCION, A.NIVEL
                """;
        } else if ("premio_escala".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    D.DESCRIPCION AS OPERACION,
                    D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPOPRODUCTIVO,
                    E.NIVEL,
                    E.DESDE AS DESDE_ACTUAL,
                    E.HASTA AS HASTA_ACTUAL,
                    E.PREMIO AS PREMIO_ACTUAL,
                    ROUND(E.DESDE/8, 0) AS DESDE_X_HORA,
                    ROUND(E.HASTA/8, 0) AS HASTA_X_HORA,
                    ROUND(E.PREMIO/8, 0) AS PREMIO_X_HORA
                FROM PV_ESCALA_DE_PREMIOS E
                JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
                WHERE E.ID_DE_GRUPO_DE_FUNCIONES = ?
                ORDER BY 1, 3, 4
                """;
        } else if ("premio_pago_actual".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    A.LEGAJO, " +
                "    D.DESCRIPCION AS OPERACION, " +
                "    C.PROD_REAL AS PRODUCTIVIDAD, " +
                "    B.A_PAGAR_TOTAL, " +
                "    B.ID_PV_UNIDAD_DE_PRODUCCION AS ULMEDIDA " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES " +
                "JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL " +
                "WHERE A.FECHA = ? " +
                "  AND D.DESCRIPCION = ? " +
                "  AND E.NIVEL = ? " +
                "  AND A.LEGAJO IN (" + placeholders(legajo) + ") " +
                "ORDER BY A.LEGAJO";
        } else if ("premio_produccion_hora".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH TODO AS ( " +
                "SELECT " +
                "    TO_CHAR(TO_DATE(?, 'YYYY-MM-DD'), 'YYYY-MM-DD') AS fecha, " +
                "    TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS hora, " +
                "    COPECREA AS OPERARIO, " +
                "    UPPER(CDESCRIP) AS OPERACION, " +
                "    SUM(QCANTIDA) AS CANTIDAD, " +
                "    CASE SUB1.DESCDIVI " +
                "        WHEN 'SECTOR SECOS' THEN 'SECOS + NOA ' " +
                "        WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA ' " +
                "        ELSE SUB1.DESCDIVI " +
                "    END AS ALMACEN " +
                "FROM F132HIST A " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND COPECREA IN (" + placeholders(legajo) + ") " +
                "  AND UPPER(CDESCRIP) = ? " +
                "GROUP BY " +
                "    TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')), " +
                "    COPECREA, " +
                "    UPPER(CDESCRIP), " +
                "    CASE SUB1.DESCDIVI " +
                "        WHEN 'SECTOR SECOS' THEN 'SECOS + NOA ' " +
                "        WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA ' " +
                "        ELSE SUB1.DESCDIVI " +
                "    END " +
                "ORDER BY TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) " +
                ") SELECT * FROM TODO";
        } else if ("pp_premio_escalas".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    D.DESCRIPCION AS OPERACION,
                    D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPOPRODUCTIVO,
                    E.NIVEL,
                    E.DESDE AS DESDE_ACTUAL,
                    E.HASTA AS HASTA_ACTUAL,
                    E.PREMIO AS PREMIO_ACTUAL,
                    ROUND(E.DESDE / 8, 0) AS DESDE_X_HORA,
                    ROUND(E.HASTA / 8, 0) AS HASTA_X_HORA,
                    ROUND(E.PREMIO / 8, 0) AS PREMIO_X_HORA,
                    E.ID_DE_GRUPO_PRODUCTIVO,
                    E.ID_DE_GRUPO_DE_FUNCIONES
                FROM PV_ESCALA_DE_PREMIOS E
                JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
                WHERE D.DESCRIPCION = ?
                ORDER BY D.DESCRIPCION, F.DESCRIPCION, E.NIVEL
                """;
        } else if ("pp_premio_escalas_por_id".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    ? AS OPERACION,
                    D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPOPRODUCTIVO,
                    E.NIVEL,
                    E.DESDE AS DESDE_ACTUAL,
                    E.HASTA AS HASTA_ACTUAL,
                    E.PREMIO AS PREMIO_ACTUAL,
                    ROUND(E.DESDE / 8, 0) AS DESDE_X_HORA,
                    ROUND(E.HASTA / 8, 0) AS HASTA_X_HORA,
                    ROUND(E.PREMIO / 8, 0) AS PREMIO_X_HORA,
                    E.ID_DE_GRUPO_PRODUCTIVO,
                    E.ID_DE_GRUPO_DE_FUNCIONES
                FROM PV_ESCALA_DE_PREMIOS E
                JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID
                WHERE E.ID_DE_GRUPO_DE_FUNCIONES = ?
                ORDER BY NVL(F.DESCRIPCION, 'TODOS'), E.NIVEL
                """;
        } else if ("pp_premio_etapas_hora".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH FECHA_PARAM AS (
                    SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE
                    FROM DUAL
                ),
                PARAMS AS (
                    SELECT
                        FECHA_BASE,
                        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
                        ? AS OPERACION
                    FROM FECHA_PARAM
                ),
                ETAPAS AS (
                    SELECT
                        D.DESCRIPCION AS OPERACION,
                        Z.LEGAJO,
                        Z.TURNO,
                        Z.ID AS ID_PV_DIA_LABORAL,
                        A.FYHFIN,
                        TRUNC(PARA.FECHA_BASE) AS FECHA,
                        TO_NUMBER(TO_CHAR(A.FYHFIN, 'HH24')) AS HORA,
                        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                        A.PRODUCCION_REAL AS PROD_REAL,
                        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
                        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
                        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION,
                        A.PRODUCCION_EQUIV_POR_SECTOR
                          + A.PRODUCCION_EQUIV_POR_TRASLADO
                          + A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_FINAL
                    FROM PARAMS PARA
                    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
                    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
                    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
                    JOIN PV_GRUPO_DE_FUNCIONES_CAB D
                      ON D.ID = C.ID_PV_GRUPO_DE_FUNCIONES_CAB
                     AND D.DESCRIPCION = PARA.OPERACION
                )
                SELECT
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    A.FECHA,
                    A.HORA,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0) AS ID_PV_GRUPO_PRODUCTIVO,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPO_PRODUCTIVO,
                    SUM(A.PROD_REAL) AS PROD_REAL,
                    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
                    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
                    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
                    SUM(A.PROD_FINAL) AS PROD_FINAL
                FROM ETAPAS A
                JOIN PV_LIQUIDAC_DIA_DET1 E
                  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
                 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
                GROUP BY
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    A.FECHA,
                    A.HORA,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0),
                    NVL(F.DESCRIPCION, 'TODOS')
                ORDER BY A.LEGAJO, NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0), A.HORA
                """;
        } else if ("pp_premio_etapas_hora_por_id".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH FECHA_PARAM AS (
                    SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE
                    FROM DUAL
                ),
                PARAMS AS (
                    SELECT
                        FECHA_BASE,
                        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
                        ? AS OPERACION,
                        ? AS ID_GRUPO_FUNCIONES
                    FROM FECHA_PARAM
                ),
                ETAPAS AS (
                    SELECT
                        PARA.OPERACION AS OPERACION,
                        Z.LEGAJO,
                        Z.TURNO,
                        Z.ID AS ID_PV_DIA_LABORAL,
                        A.FYHFIN,
                        TRUNC(PARA.FECHA_BASE) AS FECHA,
                        TO_NUMBER(TO_CHAR(A.FYHFIN, 'HH24')) AS HORA,
                        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                        A.PRODUCCION_REAL AS PROD_REAL,
                        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
                        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
                        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION,
                        A.PRODUCCION_EQUIV_POR_SECTOR
                          + A.PRODUCCION_EQUIV_POR_TRASLADO
                          + A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_FINAL
                    FROM PARAMS PARA
                    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
                    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
                    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
                    WHERE C.ID_PV_GRUPO_DE_FUNCIONES_CAB = TO_NUMBER(PARA.ID_GRUPO_FUNCIONES)
                )
                SELECT
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    A.FECHA,
                    A.HORA,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0) AS ID_PV_GRUPO_PRODUCTIVO,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPO_PRODUCTIVO,
                    SUM(A.PROD_REAL) AS PROD_REAL,
                    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
                    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
                    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
                    SUM(A.PROD_FINAL) AS PROD_FINAL
                FROM ETAPAS A
                JOIN PV_LIQUIDAC_DIA_DET1 E
                  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
                 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
                GROUP BY
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    A.FECHA,
                    A.HORA,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0),
                    NVL(F.DESCRIPCION, 'TODOS')
                ORDER BY A.LEGAJO, NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0), A.HORA
                """;
        } else if ("pp_premio_liquidacion_dia".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH FECHA_PARAM AS (
                    SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE
                    FROM DUAL
                ),
                PARAMS AS (
                    SELECT
                        FECHA_BASE,
                        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
                        ? AS OPERACION
                    FROM FECHA_PARAM
                ),
                ETAPAS AS (
                    SELECT
                        D.DESCRIPCION AS OPERACION,
                        Z.LEGAJO,
                        Z.TURNO,
                        Z.ID AS ID_PV_DIA_LABORAL,
                        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                        A.PRODUCCION_REAL AS PROD_REAL,
                        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
                        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
                        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION
                    FROM PARAMS PARA
                    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
                    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
                    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
                    JOIN PV_GRUPO_DE_FUNCIONES_CAB D
                      ON D.ID = C.ID_PV_GRUPO_DE_FUNCIONES_CAB
                     AND D.DESCRIPCION = PARA.OPERACION
                )
                SELECT
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    ROUND(E.A_PAGAR_TOTAL, 0) AS PREMIO,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPO_PRODUCTIVO,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0) AS ID_PV_GRUPO_PRODUCTIVO,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    SUM(A.PROD_REAL) AS PROD_REAL,
                    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
                    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
                    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
                    SUM(A.PROD_EQUIV_SECTOR + A.PROD_TRASLADO + A.PROD_CONSOLIDACION) AS PROD_FINAL,
                    NVL(E.PENALIZACION_EXCESO_TNC, 0) AS PENA_TNC,
                    NVL(E.PENALIZACION_POR_ERROR, 0) AS PENA_ERROR
                FROM ETAPAS A
                JOIN PV_LIQUIDAC_DIA_DET1 E
                  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
                 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
                GROUP BY
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    E.A_PAGAR_TOTAL,
                    NVL(F.DESCRIPCION, 'TODOS'),
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0),
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    E.PENALIZACION_EXCESO_TNC,
                    E.PENALIZACION_POR_ERROR
                ORDER BY A.LEGAJO, NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0)
                """;
        } else if ("pp_premio_liquidacion_dia_por_id".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH FECHA_PARAM AS (
                    SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE
                    FROM DUAL
                ),
                PARAMS AS (
                    SELECT
                        FECHA_BASE,
                        TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO,
                        ? AS OPERACION,
                        ? AS ID_GRUPO_FUNCIONES
                    FROM FECHA_PARAM
                ),
                ETAPAS AS (
                    SELECT
                        PARA.OPERACION AS OPERACION,
                        Z.LEGAJO,
                        Z.TURNO,
                        Z.ID AS ID_PV_DIA_LABORAL,
                        C.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                        A.PRODUCCION_REAL AS PROD_REAL,
                        A.PRODUCCION_EQUIV_POR_SECTOR AS PROD_EQUIV_SECTOR,
                        A.PRODUCCION_EQUIV_POR_TRASLADO AS PROD_TRASLADO,
                        A.PROD_EQUIVAL_POR_CONSOLIDACION AS PROD_CONSOLIDACION
                    FROM PARAMS PARA
                    JOIN PV_DIA_LABORAL Z ON PARA.FECHA_PREMIO = Z.FECHA
                    JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                    JOIN PV_FUNCION B ON A.COD_FUNCION = B.CODIGO
                    JOIN PV_GRUPO_DE_FUNCIONES_DET C ON C.ID_PV_FUNCION = B.ID
                    WHERE C.ID_PV_GRUPO_DE_FUNCIONES_CAB = TO_NUMBER(PARA.ID_GRUPO_FUNCIONES)
                )
                SELECT
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    ROUND(E.A_PAGAR_TOTAL, 0) AS PREMIO,
                    NVL(F.DESCRIPCION, 'TODOS') AS GRUPO_PRODUCTIVO,
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0) AS ID_PV_GRUPO_PRODUCTIVO,
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    SUM(A.PROD_REAL) AS PROD_REAL,
                    SUM(A.PROD_EQUIV_SECTOR) AS PROD_EQUIV_SECTOR,
                    SUM(A.PROD_TRASLADO) AS PROD_TRASLADO,
                    SUM(A.PROD_CONSOLIDACION) AS PROD_CONSOLIDACION,
                    SUM(A.PROD_EQUIV_SECTOR + A.PROD_TRASLADO + A.PROD_CONSOLIDACION) AS PROD_FINAL,
                    NVL(E.PENALIZACION_EXCESO_TNC, 0) AS PENA_TNC,
                    NVL(E.PENALIZACION_POR_ERROR, 0) AS PENA_ERROR
                FROM ETAPAS A
                JOIN PV_LIQUIDAC_DIA_DET1 E
                  ON A.ID_PV_DIA_LABORAL = E.ID_PV_DIA_LABORAL
                 AND E.ID_PV_GRUPO_DE_FUNCIONES = A.ID_PV_GRUPO_DE_FUNCIONES_CAB
                LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_PV_GRUPO_PRODUCTIVO = F.ID
                GROUP BY
                    A.OPERACION,
                    A.LEGAJO,
                    A.TURNO,
                    A.ID_PV_DIA_LABORAL,
                    E.A_PAGAR_TOTAL,
                    NVL(F.DESCRIPCION, 'TODOS'),
                    NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0),
                    A.ID_PV_GRUPO_DE_FUNCIONES_CAB,
                    E.PENALIZACION_EXCESO_TNC,
                    E.PENALIZACION_POR_ERROR
                ORDER BY A.LEGAJO, NVL(E.ID_PV_GRUPO_PRODUCTIVO, 0)
                """;
        } else if ("pv_grupo_funciones_catalogo".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    D.ID AS ID_GRUPO_FUNCIONES,
                    D.DESCRIPCION AS OPERACION_CAB,
                    D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA,
                    COUNT(E.ID_DE_GRUPO_DE_FUNCIONES) AS FILAS_ESCALA,
                    MIN(E.ID_DE_GRUPO_PRODUCTIVO) AS MIN_GRUPO_PRODUCTIVO,
                    MAX(E.ID_DE_GRUPO_PRODUCTIVO) AS MAX_GRUPO_PRODUCTIVO
                FROM PV_GRUPO_DE_FUNCIONES_CAB D
                LEFT JOIN PV_ESCALA_DE_PREMIOS E ON E.ID_DE_GRUPO_DE_FUNCIONES = D.ID
                WHERE D.ID IN (1, 2, 3, 4, 241)
                   OR UPPER(D.DESCRIPCION) LIKE '%CARRE%'
                   OR UPPER(D.DESCRIPCION) LIKE '%TRASLADO%'
                   OR UPPER(D.DESCRIPCION) LIKE '%CONSOLID%'
                   OR UPPER(D.DESCRIPCION) LIKE '%CARGA%'
                   OR UPPER(D.DESCRIPCION) LIKE '%CLARK%'
                   OR UPPER(D.DESCRIPCION) LIKE '%CONTROL%'
                GROUP BY D.ID, D.DESCRIPCION, D.ID_DE_UNIDAD_DE_PRODUCCION
                ORDER BY D.ID, D.DESCRIPCION
                """;
        } else if ("pv_etapas_desc_funcion_dia".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    A.DESC_FUNCION,
                    COUNT(*) AS ETAPAS,
                    COUNT(DISTINCT Z.LEGAJO) AS LEGAJOS,
                    ROUND(SUM(NVL(A.PRODUCCION_REAL, 0)), 3) AS PROD_REAL,
                    ROUND(SUM(NVL(A.PRODUCCION_EQUIV_POR_SECTOR, 0)), 3) AS PROD_EQUIV_SECTOR,
                    ROUND(SUM(NVL(A.PRODUCCION_EQUIV_POR_TRASLADO, 0)), 3) AS PROD_TRASLADO,
                    ROUND(SUM(NVL(A.PROD_EQUIVAL_POR_CONSOLIDACION, 0)), 3) AS PROD_CONSOLIDACION
                FROM PV_DIA_LABORAL Z
                JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                WHERE Z.FECHA = TO_NUMBER(TO_CHAR(TO_DATE(?, 'YYYY/MM/DD'), 'YYYYMMDD'))
                  AND (
                    UPPER(A.DESC_FUNCION) LIKE '%TRASLADO%'
                    OR UPPER(A.DESC_FUNCION) LIKE '%CARRETEO%'
                    OR UPPER(A.DESC_FUNCION) LIKE '%CONSOLIDACION%'
                  )
                GROUP BY A.DESC_FUNCION
                ORDER BY A.DESC_FUNCION
                """;
        } else if ("pv_etapas_funciones_operacion_dia".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    G.ID AS ID_GRUPO_FUNCIONES,
                    G.DESCRIPCION AS OPERACION,
                    F.CODIGO,
                    F.DESCRIPCION AS FUNCION,
                    COUNT(*) AS ETAPAS,
                    COUNT(DISTINCT Z.LEGAJO) AS LEGAJOS,
                    ROUND(SUM(NVL(A.PRODUCCION_REAL, 0)), 3) AS PROD_REAL,
                    ROUND(SUM(NVL(A.PRODUCCION_EQUIV_POR_SECTOR, 0)), 3) AS PROD_EQUIV_SECTOR,
                    ROUND(SUM(NVL(A.PRODUCCION_EQUIV_POR_TRASLADO, 0)), 3) AS PROD_TRASLADO,
                    ROUND(SUM(NVL(A.PROD_EQUIVAL_POR_CONSOLIDACION, 0)), 3) AS PROD_CONSOLIDACION,
                    ROUND(SUM(
                        NVL(A.PRODUCCION_EQUIV_POR_SECTOR, 0)
                      + NVL(A.PRODUCCION_EQUIV_POR_TRASLADO, 0)
                      + NVL(A.PROD_EQUIVAL_POR_CONSOLIDACION, 0)
                    ), 3) AS PROD_FINAL
                FROM PV_DIA_LABORAL Z
                JOIN PV_ETAPA_CAB A ON Z.ID = A.ID_PV_DIA_LABORAL
                JOIN PV_FUNCION F ON A.COD_FUNCION = F.CODIGO
                JOIN PV_GRUPO_DE_FUNCIONES_DET GD ON GD.ID_PV_FUNCION = F.ID
                JOIN PV_GRUPO_DE_FUNCIONES_CAB G ON G.ID = GD.ID_PV_GRUPO_DE_FUNCIONES_CAB
                WHERE Z.FECHA = TO_NUMBER(TO_CHAR(TO_DATE(?, 'YYYY/MM/DD'), 'YYYYMMDD'))
                  AND G.DESCRIPCION = ?
                GROUP BY G.ID, G.DESCRIPCION, F.CODIGO, F.DESCRIPCION
                ORDER BY F.CODIGO
                """;
        } else if ("pv_liquidacion_grupo_dia".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                    B.ID_PV_GRUPO_DE_FUNCIONES,
                    COUNT(*) AS FILAS,
                    COUNT(DISTINCT A.LEGAJO) AS LEGAJOS,
                    ROUND(SUM(NVL(B.A_PAGAR_TOTAL, 0)), 2) AS A_PAGAR_TOTAL,
                    ROUND(SUM(NVL(B.PENALIZACION_EXCESO_TNC, 0)), 2) AS PENA_TNC,
                    ROUND(SUM(NVL(B.PENALIZACION_POR_ERROR, 0)), 2) AS PENA_ERROR,
                    MIN(B.OBJETIVO_NIVEL_ALCANZADO) AS MIN_NIVEL,
                    MAX(B.OBJETIVO_NIVEL_ALCANZADO) AS MAX_NIVEL,
                    MIN(B.ID_PV_GRUPO_PRODUCTIVO) AS MIN_GRUPO_PRODUCTIVO,
                    MAX(B.ID_PV_GRUPO_PRODUCTIVO) AS MAX_GRUPO_PRODUCTIVO
                FROM PV_DIA_LABORAL A
                JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL
                WHERE A.FECHA = TO_NUMBER(TO_CHAR(TO_DATE(?, 'YYYY/MM/DD'), 'YYYYMMDD'))
                  AND B.ID_PV_GRUPO_DE_FUNCIONES = TO_NUMBER(?)
                GROUP BY B.ID_PV_GRUPO_DE_FUNCIONES
                """;
        } else if ("pp_estudio_premios_oracle".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH PARAMS AS (
                    SELECT
                        TO_NUMBER(TO_CHAR(TO_DATE(?, 'YYYY/MM/DD'), 'YYYYMMDD')) AS FECHA_DESDE,
                        TO_NUMBER(TO_CHAR(TO_DATE(?, 'YYYY/MM/DD'), 'YYYYMMDD')) AS FECHA_HASTA
                    FROM DUAL
                ),
                BASE AS (
                    SELECT
                        A.LEGAJO,
                        A.FECHA,
                        D.ID AS ID_GRUPO_FUNCIONES,
                        D.DESCRIPCION AS OPERACION,
                        NVL(D.ID_DE_UNIDAD_DE_PRODUCCION, 'NA') AS UNIDAD_MEDIDA,
                        CASE
                            WHEN NVL(D.ID_DE_UNIDAD_DE_PRODUCCION, 'NA') = 'NA' THEN 'NO MEDIBLE'
                            ELSE 'MEDIBLE'
                        END AS TIPO_PREMIO,
                        NVL(F.DESCRIPCION, 'TODOS') AS DIVISION,
                        NVL(B.A_PAGAR_TOTAL, 0) AS PAGO,
                        NVL(C.PROD_REAL, 0) AS PROD,
                        NVL(B.PENALIZACION_EXCESO_TNC, 0) AS PENA_TNC,
                        NVL(B.PENALIZACION_POR_ERROR, 0) AS PENA_ERROR
                    FROM PARAMS P
                    JOIN PV_DIA_LABORAL A
                      ON A.FECHA BETWEEN P.FECHA_DESDE AND P.FECHA_HASTA
                    JOIN PV_LIQUIDAC_DIA_DET1 B
                      ON A.ID = B.ID_PV_DIA_LABORAL
                    JOIN PV_GRUPO_DE_FUNCIONES_CAB D
                      ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES
                    LEFT JOIN PV_GRUPO_PRODUCTIVO_CAB F
                      ON B.ID_PV_GRUPO_PRODUCTIVO = F.ID
                    LEFT JOIN PV_LIQUIDAC_DIA_DET2 C
                      ON A.ID = C.ID_PV_DIA_LABORAL
                     AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES
                     AND NVL(B.ID_PV_GRUPO_PRODUCTIVO, 0) = NVL(C.ID_PV_GRUPO_PRODUCTIVO, 0)
                )
                SELECT
                    LEGAJO,
                    FECHA,
                    OPERACION,
                    UNIDAD_MEDIDA,
                    TIPO_PREMIO,
                    DIVISION,
                    COUNT(*) AS JORNADAS_CON_MEDICION,
                    COUNT(DISTINCT FECHA) AS DIAS_CON_MEDICION,
                    SUM(CASE WHEN PAGO > 0 THEN 1 ELSE 0 END) AS JORNADAS_CON_PREMIO,
                    SUM(CASE WHEN PROD > 0 THEN 1 ELSE 0 END) AS JORNADAS_CON_ACTIVIDAD,
                    SUM(CASE WHEN PROD > 0 AND PAGO <= 0 THEN 1 ELSE 0 END) AS JORNADAS_ACTIVIDAD_SIN_PREMIO,
                    SUM(CASE WHEN PROD <= 0 AND PAGO > 0 THEN 1 ELSE 0 END) AS JORNADAS_PREMIO_SIN_ACTIVIDAD,
                    ROUND(SUM(PAGO), 2) AS PREMIO_ACTUAL_TOTAL,
                    ROUND(SUM(PROD), 3) AS PRODUCTIVIDAD_TOTAL,
                    ROUND(SUM(PROD), 3) AS PRODUCTIVIDAD_TURNO_TOTAL
                FROM BASE
                GROUP BY LEGAJO, FECHA, OPERACION, UNIDAD_MEDIDA, TIPO_PREMIO, DIVISION
                ORDER BY PREMIO_ACTUAL_TOTAL DESC, LEGAJO, FECHA, TIPO_PREMIO, OPERACION, DIVISION
                """;
        } else if ("premio_caso_modelo_rango".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH FECHA_PARAM AS (SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE FROM DUAL), " +
                "PARAMS AS (SELECT FECHA_BASE, FECHA_BASE + (6 / 24) AS FECHA_DESDE, FECHA_BASE + 1 + (10.5 / 24) AS FECHA_HASTA, TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO FROM FECHA_PARAM), " +
                "ESCALAS AS (SELECT D.DESCRIPCION AS OPERACION, D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA, " + ALMACEN_GRUPO_SQL + " AS GRUPOPRODUCTIVO, E.NIVEL, E.DESDE AS DESDE_ACTUAL, E.HASTA AS HASTA_ACTUAL, E.PREMIO AS PREMIO_ACTUAL, ROUND(E.DESDE/8, 0) AS DESDE_X_HORA, ROUND(E.HASTA/8, 0) AS HASTA_X_HORA, ROUND(E.PREMIO/8, 0) AS PREMIO_X_HORA FROM PV_ESCALA_DE_PREMIOS E JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID WHERE E.ID_DE_GRUPO_DE_FUNCIONES = 1), " +
                "COMPARACION AS (SELECT A.FECHA, A.LEGAJO, D.DESCRIPCION AS OPERACION, C.PROD_REAL, C.PROD_REAL/8 AS PROD_REAL_X_HORA, B.A_PAGAR_TOTAL AS PREMIO_ANTERIOR_NETO, NVL(B.PENALIZACION_EXCESO_TNC, 0) AS DESCUENTO_TNC, NVL(B.PENALIZACION_POR_ERROR, 0) AS DESCUENTO_ERROR, NVL(B.PENALIZACION_EXCESO_TNC, 0) + NVL(B.PENALIZACION_POR_ERROR, 0) AS DESCUENTOS_TOTAL, B.A_PAGAR_TOTAL + NVL(B.PENALIZACION_EXCESO_TNC, 0) + NVL(B.PENALIZACION_POR_ERROR, 0) AS PREMIO_ANTERIOR_BRUTO, B.ID_PV_UNIDAD_DE_PRODUCCION, A.TURNO AS TURNOPROD FROM PV_DIA_LABORAL A JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL JOIN PV_GRUPO_PRODUCTIVO_CAB F ON C.ID_PV_GRUPO_PRODUCTIVO = F.ID JOIN PARAMS param ON A.FECHA = PARAM.FECHA_PREMIO WHERE D.DESCRIPCION = ? AND " + ALMACEN_GRUPO_SQL + " = ?), " +
                "F132_SOURCE AS (SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI FROM F132HIST A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA WHERE A.COPECREA IN (SELECT LEGAJO FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(A.CDESCRIP) = 'PICKING' UNION ALL SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI FROM F132HIST_HIST A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA WHERE A.COPECREA IN (SELECT LEGAJO FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(A.CDESCRIP) = 'PICKING' AND NOT EXISTS (SELECT 1 FROM F132HIST X JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA WHERE X.COPECREA IN (SELECT LEGAJO FROM COMPARACION) AND (X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24) OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(X.CDESCRIP) = 'PICKING')), " +
                "TODO AS (SELECT TRUNC(FECHA_DESDE) AS FECHA, TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS HORA, CASE WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 14 THEN '1' WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 22 THEN '2' ELSE '3' END AS TURNO, COPECREA AS OPERARIO, UPPER(CDESCRIP) AS OPERACION, SUM(QCANTIDA) AS CANTIDAD, " + ALMACEN_DIVISION_SQL + " AS ALMACEN FROM F132_SOURCE A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 ON SUB1.CZONALMA = A.CZONAORI WHERE COPECREA IN (SELECT LEGAJO FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(CDESCRIP) = 'PICKING' GROUP BY TRUNC(FECHA_DESDE), TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')), COPECREA, UPPER(CDESCRIP), " + ALMACEN_DIVISION_SQL + "), " +
                "TODOPREMIO AS (SELECT A.*, B.DESDE_X_HORA, B.HASTA_X_HORA, ROUND(B.PREMIO_ACTUAL/8, 2) AS PREMIO_NUEVO FROM TODO A LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN AND A.CANTIDAD > B.DESDE_X_HORA AND A.CANTIDAD <= B.HASTA_X_HORA), " +
                "AGG AS (SELECT A.*, B.TURNOPROD, B.PROD_REAL AS PRODUCTIVIDAD_ANTERIOR, B.PREMIO_ANTERIOR_NETO AS PREMIO_ANTERIOR, B.PREMIO_ANTERIOR_BRUTO, B.DESCUENTO_TNC, B.DESCUENTO_ERROR, B.DESCUENTOS_TOTAL, CASE WHEN A.TURNO = B.TURNOPROD THEN A.CANTIDAD ELSE 0 END AS DENTROTURNO FROM TODOPREMIO A JOIN COMPARACION B ON A.OPERARIO = B.LEGAJO), " +
                "FINAL AS (SELECT FECHA, OPERARIO, OPERACION, SUM(CANTIDAD) AS BULTOS, ALMACEN, SUM(PREMIO_NUEVO) AS PREMIO_X_HORAS_BRUTO, SUM(CASE WHEN TURNO = TURNOPROD THEN PREMIO_NUEVO ELSE 0 END) AS PREMIO_X_HORAS_SIN_EXT_BRUTO, PRODUCTIVIDAD_ANTERIOR, PREMIO_ANTERIOR, PREMIO_ANTERIOR_BRUTO, DESCUENTO_TNC, DESCUENTO_ERROR, DESCUENTOS_TOTAL, SUM(DENTROTURNO) AS BULTOSTURNO FROM AGG GROUP BY FECHA, OPERARIO, OPERACION, ALMACEN, PRODUCTIVIDAD_ANTERIOR, PREMIO_ANTERIOR, PREMIO_ANTERIOR_BRUTO, DESCUENTO_TNC, DESCUENTO_ERROR, DESCUENTOS_TOTAL) " +
                "SELECT DISTINCT A.FECHA, A.OPERARIO, A.OPERACION, A.BULTOS, A.ALMACEN, GREATEST(A.PREMIO_X_HORAS_BRUTO - A.DESCUENTOS_TOTAL, 0) AS PREMIO_X_HORAS, A.PREMIO_X_HORAS_BRUTO, GREATEST(A.PREMIO_X_HORAS_SIN_EXT_BRUTO - A.DESCUENTOS_TOTAL, 0) AS PREMIO_X_HORAS_SIN_EXTRAS, A.PREMIO_X_HORAS_SIN_EXT_BRUTO AS PREMIO_X_HORAS_SIN_EXTRAS_BRUTO, A.PRODUCTIVIDAD_ANTERIOR, A.PREMIO_ANTERIOR, A.PREMIO_ANTERIOR_BRUTO, A.DESCUENTO_TNC, A.DESCUENTO_ERROR, A.DESCUENTOS_TOTAL, A.BULTOSTURNO, GREATEST(B.PREMIO_ACTUAL - A.DESCUENTOS_TOTAL, 0) AS PREMIO_ACTUAL, B.PREMIO_ACTUAL AS PREMIO_ACTUAL_BRUTO, A.PREMIO_ANTERIOR - GREATEST(A.PREMIO_X_HORAS_BRUTO - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_X_HORAS, A.PREMIO_ANTERIOR - GREATEST(B.PREMIO_ACTUAL - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_SIN_EXTRAS, A.PREMIO_ANTERIOR - GREATEST(A.PREMIO_X_HORAS_SIN_EXT_BRUTO - A.DESCUENTOS_TOTAL, 0) AS DIFERENCIA_X_HORAS_SIN_EXTRAS FROM FINAL A JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN AND A.BULTOSTURNO >= B.DESDE_ACTUAL AND A.BULTOSTURNO < B.HASTA_ACTUAL ORDER BY A.FECHA, A.OPERARIO";
        } else if ("premio_caso_modelo_detalle".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH FECHA_PARAM AS (SELECT TO_DATE(?, 'YYYY/MM/DD') AS FECHA_BASE FROM DUAL), " +
                "PARAMS AS (SELECT FECHA_BASE, FECHA_BASE + (6 / 24) AS FECHA_DESDE, FECHA_BASE + 1 + (10.5 / 24) AS FECHA_HASTA, TO_NUMBER(TO_CHAR(FECHA_BASE, 'YYYYMMDD')) AS FECHA_PREMIO FROM FECHA_PARAM), " +
                "ESCALAS AS (SELECT D.DESCRIPCION AS OPERACION, D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA, " + ALMACEN_GRUPO_SQL + " AS GRUPOPRODUCTIVO, E.NIVEL, E.DESDE AS DESDE_ACTUAL, E.HASTA AS HASTA_ACTUAL, E.PREMIO AS PREMIO_ACTUAL, ROUND(E.DESDE / 8, 0) AS DESDE_X_HORA, ROUND(E.HASTA / 8, 0) AS HASTA_X_HORA, ROUND(E.PREMIO / 8, 0) AS PREMIO_X_HORA FROM PV_ESCALA_DE_PREMIOS E JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID WHERE E.ID_DE_GRUPO_DE_FUNCIONES = 1), " +
                "COMPARACION AS (SELECT A.FECHA, A.LEGAJO, D.DESCRIPCION AS OPERACION, C.PROD_REAL, C.PROD_REAL / 8 AS PROD_REAL_X_HORA, B.A_PAGAR_TOTAL, B.ID_PV_UNIDAD_DE_PRODUCCION, A.TURNO AS TURNOPROD, CASE WHEN B.PENALIZACION_EXCESO_TNC > 0 THEN 'PENALIZACION TNC' ELSE 'SIN PENALIZACION' END AS PENALIZACION_TNC, CASE WHEN B.PENALIZACION_POR_ERROR > 0 THEN 'PENALIZACION ERROR' ELSE '' END AS PENALIZACION_ERROR FROM PV_DIA_LABORAL A JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL JOIN PV_GRUPO_PRODUCTIVO_CAB F ON C.ID_PV_GRUPO_PRODUCTIVO = F.ID JOIN PARAMS PARAM ON A.FECHA = PARAM.FECHA_PREMIO WHERE D.DESCRIPCION = ? AND " + ALMACEN_GRUPO_SQL + " = ? AND A.LEGAJO = ?), " +
                "F132_SOURCE AS (SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI FROM F132HIST A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(A.CDESCRIP) = 'PICKING' UNION ALL SELECT A.FCREAREG, A.COPECREA, A.CDESCRIP, A.QCANTIDA, A.CZONAORI FROM F132HIST_HIST A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(A.CDESCRIP) = 'PICKING' AND NOT EXISTS (SELECT 1 FROM F132HIST X JOIN PARAMS P ON X.FCREAREG >= P.FECHA_DESDE AND X.FCREAREG <= P.FECHA_HASTA WHERE X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION) AND (X.FCREAREG <= P.FECHA_BASE + 1 + (6 / 24) OR X.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(X.CDESCRIP) = 'PICKING')), " +
                "TODO AS (SELECT TRUNC(B.FECHA_DESDE) AS FECHA, TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) AS HORA, CASE WHEN TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) < 14 THEN '1' WHEN TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')) < 22 THEN '2' ELSE '3' END AS TURNO, A.COPECREA AS OPERARIO, UPPER(A.CDESCRIP) AS OPERACION, SUM(A.QCANTIDA) AS CANTIDAD, " + ALMACEN_DIVISION_SQL + " AS ALMACEN FROM F132_SOURCE A JOIN PARAMS B ON A.FCREAREG >= B.FECHA_DESDE AND A.FCREAREG <= B.FECHA_HASTA LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 ON SUB1.CZONALMA = A.CZONAORI WHERE A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION) AND (A.FCREAREG <= B.FECHA_BASE + 1 + (6 / 24) OR A.COPECREA IN (SELECT TO_CHAR(LEGAJO) FROM COMPARACION WHERE TURNOPROD = '3')) AND UPPER(A.CDESCRIP) = 'PICKING' GROUP BY TRUNC(B.FECHA_DESDE), TO_NUMBER(TO_CHAR(A.FCREAREG, 'HH24')), A.COPECREA, UPPER(A.CDESCRIP), " + ALMACEN_DIVISION_SQL + "), " +
                "TODOPREMIO AS (SELECT A.*, B.DESDE_X_HORA, B.HASTA_X_HORA, ROUND(B.PREMIO_ACTUAL / 8, 2) AS PREMIO_NUEVO FROM TODO A LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN AND A.CANTIDAD > B.DESDE_X_HORA AND A.CANTIDAD <= B.HASTA_X_HORA), " +
                "AGG AS (SELECT A.*, B.TURNOPROD, B.PROD_REAL AS PRODUCTIVIDAD_ANTERIOR, B.A_PAGAR_TOTAL AS PREMIO_ANTERIOR, CASE WHEN A.TURNO = B.TURNOPROD THEN A.CANTIDAD ELSE 0 END AS DENTROTURNO, B.PENALIZACION_TNC, B.PENALIZACION_ERROR FROM TODOPREMIO A JOIN COMPARACION B ON TO_CHAR(A.OPERARIO) = TO_CHAR(B.LEGAJO)), " +
                "AGG2 AS (SELECT A.FECHA, A.HORA, CASE A.TURNO WHEN '1' THEN 'MAÑANA' WHEN '2' THEN 'TARDE' ELSE 'NOCHE' END AS TURNO, A.OPERARIO, B.NOMBRE, A.OPERACION, A.CANTIDAD AS BULTOS, A.ALMACEN, A.DESDE_X_HORA AS BULTOS_HORA_MIN, A.HASTA_X_HORA AS BULTOS_HORA_MAX, A.PREMIO_NUEVO AS PREMIO_X_HORA, A.PRODUCTIVIDAD_ANTERIOR AS PROD_MODULO, A.PREMIO_ANTERIOR AS PAGO_MODULO, A.DENTROTURNO AS BULTOS_MODULO, A.PENALIZACION_TNC, A.PENALIZACION_ERROR, SUM(A.DENTROTURNO) OVER (PARTITION BY A.OPERARIO) AS BULTOSTURNO FROM AGG A JOIN PV_LEGAJO B ON A.OPERARIO = B.LEGAJO) " +
                "SELECT A.*, B.PREMIO_ACTUAL AS PREMIO_SIN_EXTRA FROM AGG2 A JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN AND A.BULTOSTURNO >= B.DESDE_ACTUAL AND A.BULTOSTURNO < B.HASTA_ACTUAL ORDER BY A.HORA";
        } else if ("premio_caso_modelo_final".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH ESCALAS AS ( " +
                "SELECT D.DESCRIPCION AS OPERACION, D.ID_DE_UNIDAD_DE_PRODUCCION AS ULMEDIDA, F.DESCRIPCION AS GRUPOPRODUCTIVO, E.NIVEL, " +
                "       E.DESDE AS DESDE_ACTUAL, E.HASTA AS HASTA_ACTUAL, E.PREMIO AS PREMIO_ACTUAL, " +
                "       ROUND(E.DESDE/8, 0) AS DESDE_X_HORA, ROUND(E.HASTA/8, 0) AS HASTA_X_HORA, ROUND(E.PREMIO/8, 0) AS PREMIO_X_HORA " +
                "FROM PV_ESCALA_DE_PREMIOS E " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES " +
                "JOIN PV_GRUPO_PRODUCTIVO_CAB F ON E.ID_DE_GRUPO_PRODUCTIVO = F.ID " +
                "WHERE E.ID_DE_GRUPO_DE_FUNCIONES = ? " +
                "), TODO AS ( " +
                "SELECT TO_DATE(?, 'YYYY-MM-DD') AS FECHA, TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) AS HORA, " +
                "       CASE WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 6 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 14 THEN '1' " +
                "            WHEN TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) >= 14 AND TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')) < 22 THEN '2' ELSE '3' END AS TURNO, " +
                "       COPECREA AS OPERARIO, UPPER(CDESCRIP) AS OPERACION, SUM(QCANTIDA) AS CANTIDAD, " +
                "       CASE SUB1.DESCDIVI WHEN 'SECTOR SECOS' THEN 'SECOS + NOA ' WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA ' ELSE SUB1.DESCDIVI END AS ALMACEN " +
                "FROM F132HIST A " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND COPECREA IN (" + placeholders(legajo) + ") " +
                "  AND UPPER(CDESCRIP) = ? " +
                "GROUP BY TO_NUMBER(TO_CHAR(FCREAREG, 'HH24')), COPECREA, UPPER(CDESCRIP), " +
                "       CASE SUB1.DESCDIVI WHEN 'SECTOR SECOS' THEN 'SECOS + NOA ' WHEN 'VARIOS NO ALIMENTOS' THEN 'SECOS + NOA ' ELSE SUB1.DESCDIVI END " +
                "), TODOPREMIO AS ( " +
                "SELECT A.*, B.DESDE_X_HORA, B.HASTA_X_HORA, ROUND(B.PREMIO_ACTUAL/8, 2) AS PREMIO_NUEVO " +
                "FROM TODO A LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = 'SECOS + NOA ' AND A.CANTIDAD > B.DESDE_X_HORA AND A.CANTIDAD <= B.HASTA_X_HORA " +
                "), COMPARACION AS ( " +
                "SELECT A.FECHA, A.LEGAJO, D.DESCRIPCION AS OPERACION, C.PROD_REAL, C.PROD_REAL/8 AS PROD_REAL_X_HORA, " +
                "       B.A_PAGAR_TOTAL, B.ID_PV_UNIDAD_DE_PRODUCCION, TURNO AS TURNOPROD " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET1 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_LIQUIDAC_DIA_DET2 C ON A.ID = C.ID_PV_DIA_LABORAL AND B.ID_PV_GRUPO_DE_FUNCIONES = C.ID_PV_GRUPO_DE_FUNCIONES " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB D ON D.ID = B.ID_PV_GRUPO_DE_FUNCIONES " +
                "JOIN PV_ESCALA_DE_PREMIOS E ON D.ID = E.ID_DE_GRUPO_DE_FUNCIONES AND C.ID_PV_GRUPO_PRODUCTIVO = E.ID_DE_GRUPO_PRODUCTIVO AND B.OBJETIVO_NIVEL_ALCANZADO = E.NIVEL " +
                "WHERE A.FECHA = TO_CHAR(TO_DATE(?, 'YYYY-MM-DD'), 'YYYYMMDD') AND D.DESCRIPCION = ? AND A.LEGAJO IN (" + placeholders(legajo) + ") " +
                "), AGG AS ( " +
                "SELECT A.*, B.TURNOPROD, B.PROD_REAL AS PRODUCTIVIDAD_ANTERIOR, B.A_PAGAR_TOTAL AS PREMIO_ANTERIOR, " +
                "       CASE WHEN A.TURNO = B.TURNOPROD THEN A.CANTIDAD ELSE 0 END AS DENTROTURNO " +
                "FROM TODOPREMIO A JOIN COMPARACION B ON A.OPERARIO = B.LEGAJO " +
                "), FINAL AS ( " +
                "SELECT FECHA, OPERARIO, OPERACION, SUM(CANTIDAD) AS BULTOS, ALMACEN, SUM(PREMIO_NUEVO) AS PREMIO_X_HORAS, " +
                "       PRODUCTIVIDAD_ANTERIOR, PREMIO_ANTERIOR, SUM(DENTROTURNO) AS BULTOSTURNO " +
                "FROM AGG GROUP BY FECHA, OPERARIO, OPERACION, ALMACEN, PRODUCTIVIDAD_ANTERIOR, PREMIO_ANTERIOR " +
                ") " +
                "SELECT A.*, B.PREMIO_ACTUAL, A.PREMIO_ANTERIOR - A.PREMIO_X_HORAS AS DIFERENCIA_X_HORAS, " +
                "       A.PREMIO_ANTERIOR - B.PREMIO_ACTUAL AS DIFERENCIA_SIN_EXTRAS " +
                "FROM FINAL A LEFT JOIN ESCALAS B ON B.GRUPOPRODUCTIVO = A.ALMACEN AND A.BULTOSTURNO >= B.DESDE_ACTUAL AND A.BULTOSTURNO < B.HASTA_ACTUAL " +
                "ORDER BY A.OPERARIO";
        } else if ("picking_analysis".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    A.CREFEREN AS REFERENCIA " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) = 'PICKING' " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("daily_productividad_raw".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH LEGAJOS AS (
                  SELECT DISTINCT COPECREA AS LEGAJO
                  FROM f132hist A
                  WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND CDESCRIP IN (
                      'Picking',
                      'GUARADO PALETS ENTRADA',
                      'EXTRACCION DE REAPROS',
                      'EXTRACCION TRASPASOS',
                      'SURTIDO P.COMPLETOS',
                      'REVISION PALETS ENTRADA'
                    )
                ),
                mdiv AS (
                  SELECT
                    s.CREFEREN,
                    CASE d.CDIVISIO
                      WHEN 1 THEN 'SECOS'
                      WHEN 2 THEN 'REFRIGERADOS'
                      WHEN 6 THEN 'NOA'
                      WHEN 4 THEN 'REFRIGERADOS'
                    END AS ALMACEN
                  FROM f602asec s
                  JOIN F601SECT d
                    ON d.CNSECTOR = s.CNSECTOR
                   AND s.CALMACEN = d.CALMACEN
                  WHERE s.CALMACEN = '93'
                ),
                PRE AS (
                  SELECT
                    b.*,
                    l.DESC_FUNCION,
                    CASE
                      WHEN UPPER(TRIM(B.CZONAORI)) = 'T06'
                        OR (B.CZONAORI IS NOT NULL AND INSTR(UPPER(TRIM(B.CZONAORI)), 'T') > 0)
                        THEN 'REFRIGERADOS'
                      ELSE NVL(
                        c.ALMACEN,
                        CASE SUB1.CDIVISIO
                          WHEN 1 THEN 'SECOS'
                          WHEN 2 THEN 'REFRIGERADOS'
                          WHEN 6 THEN 'NOA'
                          WHEN 4 THEN 'REFRIGERADOS'
                        END
                      )
                    END AS ALMACEN
                  FROM LEGAJOS A
                  JOIN f132hist B
                    ON A.LEGAJO = B.COPECREA
                  LEFT JOIN PV_LEGAJO l
                    ON TO_CHAR(l.LEGAJO) = TO_CHAR(B.COPECREA)
                  LEFT JOIN (
                    SELECT DISTINCT CZONALMA, CDIVISIO
                    FROM VW_UBICACIONES_DIVISION
                  ) SUB1
                    ON SUB1.CZONALMA = B.CZONAORI
                  LEFT JOIN mdiv c
                    ON c.CREFEREN = B.CREFEREN
                  WHERE B.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND B.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                )
                SELECT A.*
                FROM PRE A
                ORDER BY FCREAREG
                """;
        } else if ("daily_picking_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH prm AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to,
                    15 AS tol_min
                  FROM dual
                ),
                leg AS (
                  SELECT DISTINCT h.COPECREA
                  FROM f132hist h
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                    AND h.CDESCRIP = 'Picking'
                ),
                bas AS (
                  SELECT
                    h.COPECREA,
                    h.FCREAREG,
                    h.CDESCRIP,
                    h.QCANTIDA,
                    h.CZONAORI,
                    LAG(h.FCREAREG) OVER (
                      PARTITION BY h.COPECREA
                      ORDER BY h.FCREAREG, h.ROWID
                    ) AS f_prev,
                    pv.TURNO AS tur_pv
                  FROM f132hist h
                  JOIN leg l
                    ON l.COPECREA = h.COPECREA
                  LEFT JOIN PV_DIA_LABORAL pv
                    ON TO_CHAR(pv.LEGAJO) = TO_CHAR(h.COPECREA)
                   AND pv.FECHA = TO_NUMBER(TO_CHAR(h.FCREAREG,'YYYYMMDD'))
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm) + INTERVAL '1' DAY
                ),
                enr AS (
                  SELECT
                    b.COPECREA,
                    b.FCREAREG,
                    b.CDESCRIP,
                    b.QCANTIDA,
                    b.CZONAORI,
                    b.f_prev,
                    CASE
                      WHEN b.f_prev IS NULL THEN 0
                      ELSE (b.FCREAREG - b.f_prev) * 86400
                    END AS dur_s,
                    CASE
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('06:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '060000'
                       AND b.tur_pv = 1 THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('14:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000'
                       AND b.tur_pv = 2 THEN 'TT'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('22:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000'
                       AND b.tur_pv = 3 THEN 'TN'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '060000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000' THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '140000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000' THEN 'TT'
                      ELSE 'TN'
                    END AS turno,
                    CASE
                      WHEN b.tur_pv = 1 THEN 'TM'
                      WHEN b.tur_pv = 2 THEN 'TT'
                      WHEN b.tur_pv = 3 THEN 'TN'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '060000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000' THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '140000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000' THEN 'TT'
                      ELSE 'TN'
                    END AS turno_base,
                    CASE
                      WHEN UPPER(TRIM(b.CZONAORI)) = 'T06' THEN 4
                      WHEN b.CZONAORI IS NOT NULL
                       AND INSTR(UPPER(TRIM(b.CZONAORI)), 'T') > 0 THEN 2
                      WHEN UPPER(TRIM(b.CZONAORI)) IN ('N01','N02','N04','N05','N07','N09','N10','N15') THEN 6
                      ELSE 1
                    END AS division
                  FROM bas b
                ),
                ven AS (
                  SELECT e.*
                  FROM enr e
                  WHERE e.FCREAREG >= (SELECT p_from FROM prm)
                    AND e.FCREAREG <  (SELECT p_to FROM prm)
                ),
                agt AS (
                  SELECT
                    m.COPECREA,
                    m.turno,
                    m.turno_base,
                    m.division,
                    SUM(m.QCANTIDA) AS bultos_picking,
                    SUM(m.dur_s) / 3600 AS hs_picking
                  FROM ven m
                  WHERE m.CDESCRIP = 'Picking'
                  GROUP BY
                    m.COPECREA,
                    m.turno,
                    m.turno_base,
                    m.division
                )
                SELECT
                  CASE
                    WHEN t.division = 1 THEN 'SECOS'
                    WHEN t.division = 2 THEN 'REFRIGERADOS'
                    WHEN t.division = 4 THEN 'REFRIGERADOS'
                    WHEN t.division = 6 THEN 'NOA'
                  END AS ALMACEN,
                  t.COPECREA,
                  t.turno,
                  t.turno_base,
                  t.bultos_picking,
                  t.hs_picking
                FROM agt t
                WHERE t.turno = t.turno_base
                  AND t.division IN (1, 2, 4, 6)
                ORDER BY
                  ALMACEN,
                  t.COPECREA,
                  t.turno
                """;
        } else if ("daily_recepcion_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH mdiv AS (
                  SELECT
                    s.CREFEREN,
                    d.CDIVISIO
                  FROM f602asec s
                  JOIN F601SECT d
                    ON d.CNSECTOR = s.CNSECTOR
                   AND s.CALMACEN = d.CALMACEN
                  WHERE s.CALMACEN = '93'
                ),
                Todos AS (
                  SELECT
                    CASE
                      WHEN SUB1.CDIVISIO = 1 OR SUB1.CDIVISIO = 3 THEN 'SECOS'
                      WHEN SUB1.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                      WHEN SUB1.CDIVISIO = 6 THEN 'NOA'
                      ELSE 'OTROS'
                    END AS ALMACEN,
                    COUNT(DISTINCT h.CNUPALET) AS PALLETS,
                    h.COPECREA AS LEGAJO
                  FROM f132hist h
                  LEFT JOIN mdiv SUB1
                    ON SUB1.CREFEREN = h.CREFEREN
                  WHERE h.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND h.FCREAREG <  TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND h.CDESCRIP = 'REVISION PALETS ENTRADA'
                    AND h.QCANTIDA > 0
                  GROUP BY
                    h.COPECREA,
                    CASE
                      WHEN SUB1.CDIVISIO = 1 OR SUB1.CDIVISIO = 3 THEN 'SECOS'
                      WHEN SUB1.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                      WHEN SUB1.CDIVISIO = 6 THEN 'NOA'
                      ELSE 'OTROS'
                    END
                )
                SELECT
                  ALMACEN,
                  SUM(PALLETS) AS PALLETS,
                  COUNT(DISTINCT LEGAJO) AS LEGAJOS,
                  ROUND(SUM(PALLETS) / COUNT(DISTINCT LEGAJO), 2) AS PRODUCCION
                FROM Todos
                WHERE ALMACEN IN ('SECOS', 'REFRIGERADOS', 'NOA')
                GROUP BY ALMACEN
                """;
        } else if ("daily_despacho_real".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT
                  CASE
                    WHEN a.CDIVISIO = 1 OR a.CDIVISIO = 3 THEN 'SECOS'
                    WHEN a.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                    WHEN a.CDIVISIO = 6 THEN 'NOA'
                    ELSE 'OTROS'
                  END AS ALMACEN,
                  COUNT(DISTINCT a.HOJARUTA) AS VIAJES,
                  COUNT(DISTINCT CASE
                    WHEN UPPER(TRIM(l.DESC_FUNCION)) IN (
                      'ARMADOR REFRI',
                      'ARMADOR DE REFRIGERADOS',
                      'CARGADOR (REFRIG)',
                      'ARMADOR DE SECOS',
                      'ARMADOR T06',
                      'ARMADOR DE NO ALIMENTOS',
                      'ARMADOR',
                      'CARGADOR DE SECOS'
                    ) THEN a.CARGADOR
                  END) AS CARGADORES,
                  ROUND(COUNT(DISTINCT a.HOJARUTA) / NULLIF(COUNT(DISTINCT CASE
                    WHEN UPPER(TRIM(l.DESC_FUNCION)) IN (
                      'ARMADOR REFRI',
                      'ARMADOR DE REFRIGERADOS',
                      'CARGADOR (REFRIG)',
                      'ARMADOR DE SECOS',
                      'ARMADOR T06',
                      'ARMADOR DE NO ALIMENTOS',
                      'ARMADOR',
                      'CARGADOR DE SECOS'
                    ) THEN a.CARGADOR
                  END), 0), 2) AS PRODUCCION
                FROM f922traf a
                LEFT JOIN PV_LEGAJO l
                  ON l.LEGAJO = a.CARGADOR
                WHERE a.FECIERRE >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                  AND a.FECIERRE <  TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                  AND a.CALMACEN = '93'
                GROUP BY
                  CASE
                    WHEN a.CDIVISIO = 1 OR a.CDIVISIO = 3 THEN 'SECOS'
                    WHEN a.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                    WHEN a.CDIVISIO = 6 THEN 'NOA'
                    ELSE 'OTROS'
                END
                """;
        } else if ("daily_despacho_raw".equalsIgnoreCase(queryKey)) {
            sql = """
                SELECT DISTINCT
                  CASE
                    WHEN a.CDIVISIO = 1 OR a.CDIVISIO = 3 THEN 'SECOS'
                    WHEN a.CDIVISIO IN (2, 4) THEN 'REFRIGERADOS'
                    WHEN a.CDIVISIO = 6 THEN 'NOA'
                    ELSE 'OTROS'
                  END AS ALMACEN,
                  a.HOJARUTA,
                  a.CARGADOR,
                  l.DESC_FUNCION,
                  a.FECIERRE,
                  a.CDIVISIO,
                  a.CALMACEN
                FROM f922traf a
                LEFT JOIN PV_LEGAJO l
                  ON l.LEGAJO = a.CARGADOR
                WHERE a.FECIERRE >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                  AND a.FECIERRE <  TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                  AND a.CALMACEN = '93'
                ORDER BY ALMACEN, a.CARGADOR, a.FECIERRE, a.HOJARUTA
                """;
        } else if ("plantel_optimo_demanda".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    CASE p.codigodedivision " +
                "        WHEN 1 THEN 'SECOS' " +
                "        WHEN 2 THEN 'REFRIGERADOS' " +
                "        WHEN 4 THEN 'REFRIGERADOS' " +
                "        WHEN 6 THEN 'NOA' " +
                "        ELSE 'OTROS' " +
                "    END AS almacen, " +
                "    CODIGODESECTOR AS sector, " +
                "    CASE WHEN p.TIPO LIKE '%PICKING%' THEN 'PICKING' END AS tipo, " +
                "    COUNT(DISTINCT P.NUMERO) AS cantidad_pallet, " +
                "    SUM(d.cantidad) AS bultos_pallet, " +
                "    TO_NUMBER(TO_CHAR(v.FECHAYHORADEINICIO, 'HH24')) AS hora " +
                "FROM TR_VIAJE v " +
                "JOIN TR_CARGAS c ON v.CODIGO = c.CODIGODEVIAJE " +
                "JOIN TR_PALLET p ON c.NUMERODEPALLET = p.NUMERO " +
                "JOIN TR_DETALLE_DE_PALLET_NEW d ON d.pallet_id = p.NUMERO " +
                "WHERE v.FECHAYHORADEINICIO >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND v.FECHAYHORADEINICIO <  TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND p.TIPO LIKE '%PICKIN%' " +
                "GROUP BY " +
                "    CODIGODESECTOR, " +
                "    TO_NUMBER(TO_CHAR(v.FECHAYHORADEINICIO, 'HH24')), " +
                "    CASE p.codigodedivision " +
                "        WHEN 1 THEN 'SECOS' " +
                "        WHEN 2 THEN 'REFRIGERADOS' " +
                "        WHEN 4 THEN 'REFRIGERADOS' " +
                "        WHEN 6 THEN 'NOA' " +
                "        ELSE 'OTROS' " +
                "    END, " +
                "    CASE WHEN p.TIPO LIKE '%PICKING%' THEN 'PICKING' END " +
                "ORDER BY almacen, sector, hora";
        } else if ("daily_planificacion".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH mdiv AS (
                  SELECT
                    s.CREFEREN,
                    d.CDIVISIO
                  FROM f602asec s
                  JOIN F601SECT d
                    ON d.CNSECTOR = s.CNSECTOR
                   AND s.CALMACEN = d.CALMACEN
                  WHERE s.CALMACEN = '93'
                ),
                base AS (
                  SELECT
                    v.CODIGO AS CODIGODEVIAJE,
                    CASE
                      WHEN p.TIPO = 'PALLET DE PICKING' THEN 'PICKING'
                      WHEN p.TIPO = 'PALLET DE PICKING (CONSOLIDADO)' THEN 'PICKING'
                      ELSE 'SURTIDO PALLET COMPLETO'
                    END AS TIPO,
                    d.PALLET_ID,
                    d.CANTIDAD,
                    CASE z.CDIVISIO
                      WHEN 1 THEN 'SECOS'
                      WHEN 2 THEN 'REFRIGERADOS'
                      WHEN 4 THEN 'REFRIGERADOS'
                      WHEN 6 THEN 'NOA'
                      ELSE TO_CHAR(z.CDIVISIO)
                    END AS ALMACEN
                  FROM TR_VIAJE v
                  JOIN TR_CARGAS c
                    ON v.CODIGO = c.CODIGODEVIAJE
                  JOIN TR_PALLET p
                    ON c.NUMERODEPALLET = p.NUMERO
                  JOIN TR_DETALLE_DE_PALLET_NEW d
                    ON d.PALLET_ID = p.NUMERO
                  JOIN mdiv z
                    ON z.CREFEREN = d.PLU
                  WHERE v.FECHAYHORADEINICIO >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                    AND v.FECHAYHORADEINICIO <  TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS')
                )
                SELECT
                  ALMACEN,
                  COUNT(DISTINCT CODIGODEVIAJE) AS VIAJES_PLANIFICADOS,
                  COUNT(DISTINCT CASE WHEN TIPO = 'PICKING' THEN PALLET_ID END) AS PALLETS_PICKING_PLANIFICADOS,
                  SUM(CASE WHEN TIPO = 'PICKING' THEN CANTIDAD ELSE 0 END) AS BULTOS_PICKING_PLANIFICADOS,
                  COUNT(DISTINCT CASE WHEN TIPO = 'SURTIDO PALLET COMPLETO' THEN PALLET_ID END) AS PALLETS_SPC_PLANIFICADOS,
                  SUM(CASE WHEN TIPO = 'SURTIDO PALLET COMPLETO' THEN CANTIDAD ELSE 0 END) AS BULTOS_SPC_PLANIFICADOS
                FROM base
                WHERE ALMACEN IN ('SECOS', 'REFRIGERADOS', 'NOA')
                GROUP BY ALMACEN
                """;
        } else if ("daily_picking_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    v.FECHAYHORADEINICIO,
                    (v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) AS FECHA_ARMADO_PLAN,
                    TRUNC((v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) - INTERVAL '6' HOUR) AS dia_operativo,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA = 1 THEN 1
                      WHEN v.CODIGODETIPODEDARSENA IN (2, 4) THEN 2
                      WHEN v.CODIGODETIPODEDARSENA = 6 THEN 6
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v, params p
                  WHERE v.FECHAYHORADEINICIO >= p.p_from
                    AND v.FECHAYHORADEINICIO <  p.p_to
                ),
                viaje_pallet AS (
                  SELECT
                    m.CODIGO AS CODIGODEVIAJE,
                    m.division,
                    c.NUMERODEPALLET AS PALLET_ID,
                    NVL(
                      (SELECT SUM(d.cantidad)
                       FROM TR_DETALLE_DE_PALLET_NEW d
                       WHERE d.pallet_id = p.NUMERO),
                      0
                    ) AS bultos_pallet
                  FROM base m
                  JOIN TR_CARGAS c ON m.CODIGO = c.CODIGODEVIAJE
                  JOIN TR_PALLET p ON c.NUMERODEPALLET = p.NUMERO
                  WHERE UPPER(p.TIPO) IN ('PALLET DE PICKING','PALLET DE PICKING (CONSOLIDADO)')
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                    WHEN 6 THEN 'NOA'
                  END AS ALMACEN,
                  SUM(bultos_pallet) AS BULTOS_PLANIFICADOS,
                  COUNT(DISTINCT CODIGODEVIAJE) AS VIAJES_PLANIFICADOS,
                  COUNT(DISTINCT PALLET_ID) AS PALLETS_PICKING_PLANIFICADOS
                FROM viaje_pallet
                WHERE division IN (1, 2, 6)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                  WHEN 6 THEN 'NOA'
                END
                """;
        } else if ("daily_despacho_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA = 1 THEN 1
                      WHEN v.CODIGODETIPODEDARSENA IN (2, 4) THEN 2
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v
                  WHERE v.FECHAYHORADEINICIO >= (SELECT p_from FROM params)
                    AND v.FECHAYHORADEINICIO <  (SELECT p_to FROM params)
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                  END AS ALMACEN,
                  COUNT(*) AS VIAJES_PLANIFICADOS
                FROM base
                WHERE division IN (1, 2)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                END
                """;
        } else if ("daily_spc_plan".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH params AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to
                  FROM dual
                ),
                base AS (
                  SELECT
                    v.CODIGO,
                    v.FECHAYHORADEINICIO,
                    v.CODIGODETIPODEDARSENA,
                    (v.FECHAYHORADEINICIO - INTERVAL '2' HOUR) AS FECHA_ARMADO_PLAN,
                    CASE
                      WHEN v.CODIGODETIPODEDARSENA = 1 THEN 1
                      WHEN v.CODIGODETIPODEDARSENA IN (2, 4) THEN 2
                      ELSE NULL
                    END AS division
                  FROM TR_VIAJE v
                  WHERE v.FECHAYHORADEINICIO >= (SELECT p_from FROM params)
                    AND v.FECHAYHORADEINICIO <  (SELECT p_to FROM params)
                ),
                viaje_pallet AS (
                  SELECT
                    m.division,
                    m.CODIGO AS CODIGODEVIAJE,
                    c.NUMERODEPALLET AS PALLET_ID,
                    p.TIPO
                  FROM base m
                  JOIN TR_CARGAS c
                    ON m.CODIGO = c.CODIGODEVIAJE
                  JOIN TR_PALLET p
                    ON c.NUMERODEPALLET = p.NUMERO
                ),
                no_picking AS (
                  SELECT *
                  FROM viaje_pallet
                  WHERE UPPER(TIPO) NOT IN ('PALLET DE PICKING','PALLET DE PICKING (CONSOLIDADO)')
                )
                SELECT
                  CASE division
                    WHEN 1 THEN 'SECOS'
                    WHEN 2 THEN 'REFRIGERADOS'
                  END AS ALMACEN,
                  COUNT(DISTINCT PALLET_ID) AS PALLETS_TOTALES_PLANIFICADOS,
                  COUNT(DISTINCT CODIGODEVIAJE) AS VIAJES_PLANIFICADOS
                FROM no_picking
                WHERE division IN (1, 2)
                GROUP BY CASE division
                  WHEN 1 THEN 'SECOS'
                  WHEN 2 THEN 'REFRIGERADOS'
                END
                """;
        } else if ("daily_clark_real".equalsIgnoreCase(queryKey)) {
            sql = """
                WITH prm AS (
                  SELECT
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_from,
                    TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS p_to,
                    15 AS tol_min
                  FROM dual
                ),
                mdiv AS (
                  SELECT
                    s.CREFEREN,
                    d.CDIVISIO
                  FROM f602asec s
                  JOIN F601SECT d
                    ON d.CNSECTOR = s.CNSECTOR
                ),
                leg AS (
                  SELECT DISTINCT h.COPECREA
                  FROM f132hist h
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                    AND h.CDESCRIP IN (
                      'GUARADO PALETS ENTRADA',
                      'EXTRACCION DE REAPROS',
                      'EXTRACCION TRASPASOS',
                      'SURTIDO P.COMPLETOS'
                    )
                ),
                bas AS (
                  SELECT
                    h.COPECREA,
                    h.FCREAREG,
                    h.CDESCRIP,
                    h.CNUPALET,
                    h.CREFEREN,
                    pv.TURNO AS tur_pv
                  FROM f132hist h
                  JOIN leg l
                    ON l.COPECREA = h.COPECREA
                  LEFT JOIN PV_DIA_LABORAL pv
                    ON TO_CHAR(pv.LEGAJO) = TO_CHAR(h.COPECREA)
                   AND pv.FECHA = TO_NUMBER(TO_CHAR(h.FCREAREG,'YYYYMMDD'))
                  WHERE h.FCREAREG >= (SELECT p_from FROM prm)
                    AND h.FCREAREG <  (SELECT p_to FROM prm)
                ),
                enr AS (
                  SELECT
                    b.COPECREA,
                    b.FCREAREG,
                    b.CDESCRIP,
                    b.CNUPALET,
                    b.CREFEREN,
                    CASE
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('06:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '060000'
                       AND b.tur_pv = 1 THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('14:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000'
                       AND b.tur_pv = 2 THEN 'TT'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= TO_CHAR(TO_DATE('22:00:00','HH24:MI:SS') - NUMTODSINTERVAL((SELECT tol_min FROM prm),'MINUTE'),'HH24MISS')
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000'
                       AND b.tur_pv = 3 THEN 'TN'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '060000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '140000' THEN 'TM'
                      WHEN TO_CHAR(b.FCREAREG,'HH24MISS') >= '140000'
                       AND TO_CHAR(b.FCREAREG,'HH24MISS') <  '220000' THEN 'TT'
                      ELSE 'TN'
                    END AS turno,
                    m.CDIVISIO AS division
                  FROM bas b
                  LEFT JOIN mdiv m
                    ON m.CREFEREN = b.CREFEREN
                ),
                ven AS (
                  SELECT
                    e.*,
                    CASE
                      WHEN e.turno = 'TM'
                       AND TO_CHAR(e.FCREAREG,'HH24MISS') < '060000'
                      THEN TRUNC(e.FCREAREG)
                      ELSE TRUNC(e.FCREAREG - INTERVAL '6' HOUR)
                    END AS dia_op
                  FROM enr e
                  WHERE e.FCREAREG >= (SELECT p_from FROM prm)
                    AND e.FCREAREG <  (SELECT p_to FROM prm)
                ),
                seq AS (
                  SELECT
                    v.*,
                    LAG(v.FCREAREG) OVER (
                      PARTITION BY v.COPECREA,
                        CASE
                          WHEN v.turno = 'TM' AND TO_CHAR(v.FCREAREG,'HH24MISS') < '060000' THEN TRUNC(v.FCREAREG)
                          ELSE TRUNC(v.FCREAREG - INTERVAL '6' HOUR)
                        END,
                        v.turno
                      ORDER BY v.FCREAREG, v.CDESCRIP, v.CNUPALET, v.CREFEREN
                    ) AS f_prev_turno
                  FROM ven v
                ),
                dur AS (
                  SELECT
                    s.*,
                    CASE
                      WHEN s.f_prev_turno IS NULL THEN 0
                      ELSE (s.FCREAREG - s.f_prev_turno) * 86400
                    END AS dur_s_turno
                  FROM seq s
                ),
                clk AS (
                  SELECT *
                  FROM dur
                  WHERE CDESCRIP IN (
                    'GUARADO PALETS ENTRADA',
                    'EXTRACCION DE REAPROS',
                    'EXTRACCION TRASPASOS',
                    'SURTIDO P.COMPLETOS'
                  )
                ),
                agt AS (
                  SELECT
                    m.COPECREA,
                    m.turno,
                    m.division,
                    COUNT(m.CNUPALET) AS pallets_totales,
                    SUM(m.dur_s_turno) / 3600 AS hs_clark_total,
                    COUNT(CASE WHEN m.CDESCRIP = 'SURTIDO P.COMPLETOS' THEN m.CNUPALET END) AS pallets_tot_surtido
                  FROM clk m
                  GROUP BY
                    m.COPECREA,
                    m.turno,
                    m.division
                )
                SELECT
                  CASE
                    WHEN t.division = 1 THEN 'SECOS'
                    WHEN t.division = 2 THEN 'REFRIGERADOS'
                    WHEN t.division = 4 THEN 'REFRIGERADOS'
                    WHEN t.division = 6 THEN 'NOA'
                  END AS ALMACEN,
                  t.COPECREA,
                  t.turno,
                  t.pallets_totales,
                  t.hs_clark_total,
                  t.pallets_tot_surtido
                FROM agt t
                WHERE t.division IN (1, 2, 4, 6)
                ORDER BY
                  ALMACEN,
                  t.COPECREA,
                  t.turno
                """;
        } else if ("gestion_productividad_picking".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT * FROM ( " +
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    'F132HIST' AS SOURCE_TABLE " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 " +
                "  ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) IN ('PICKING', 'ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "UNION ALL " +
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO, " +
                "    'F132HIST_HIST' AS SOURCE_TABLE " +
                "FROM F132HIST_HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 " +
                "  ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(A.CDESCRIP) IN ('PICKING', 'ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                ") ORDER BY COPECREA, FH_MOVIMIENTO";
        } else if ("historia_productividad_legajo".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    C.DESCRIPCION AS FUNCION, " +
                "    B.PROD_REAL, " +
                "    B.PROD_EQUIVAL_POR_SECTOR " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET2 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB C ON C.ID = B.ID_PV_GRUPO_DE_FUNCIONES " +
                "WHERE A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "  AND A.LEGAJO = ? " +
                "  AND (B.PROD_REAL > 0 OR B.PROD_EQUIVAL_POR_SECTOR > 0) " +
                "ORDER BY A.FECHA, C.DESCRIPCION";
        } else if ("historia_productividad_bulk".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    A.LEGAJO, " +
                "    SUM(B.PROD_REAL) AS PRODUCCION, " +
                "    SUM(B.TIEMPO_DURANTE_PH_EN_SEGUNDOS) AS TIEMPONETO, " +
                "    SUM(B.TIEMPO_TOTAL_EN_SEGUNDOS) AS TIEMPOTOTAL, " +
                "    C.DESCRIPCION AS FUNCION, " +
                "    C.ID_DE_UNIDAD_DE_PRODUCCION AS TIPO " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET2 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "JOIN PV_GRUPO_DE_FUNCIONES_CAB C ON B.ID_PV_GRUPO_DE_FUNCIONES = C.ID " +
                "WHERE A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "GROUP BY A.FECHA, A.LEGAJO, C.DESCRIPCION, C.ID_DE_UNIDAD_DE_PRODUCCION " +
                "ORDER BY A.FECHA, A.LEGAJO, C.DESCRIPCION";
        } else if ("historia_tnc_legajo".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FECHA, " +
                "    B.DESCRIP_DE_FUNCION, " +
                "    B.CANTIDAD_DE_CORTES_HECHOS, " +
                "    B.TIEMPO_EXCEDIDO_EN_SEGUNDOS " +
                "FROM PV_DIA_LABORAL A " +
                "JOIN PV_LIQUIDAC_DIA_DET3 B ON A.ID = B.ID_PV_DIA_LABORAL " +
                "WHERE A.LEGAJO = ? " +
                "  AND A.FECHA >= ? " +
                "  AND A.FECHA <= ? " +
                "  AND B.TIEMPO_EXCEDIDO_EN_SEGUNDOS > 0 " +
                "ORDER BY A.FECHA, B.DESCRIP_DE_FUNCION";
        } else if ("historia_actividad_operaciones".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    TO_CHAR(FCREAREG, 'YYYY-MM-DD') AS FECHA, " +
                "    CDESCRIP AS OPERACION " +
                "FROM ( " +
                "    SELECT DISTINCT TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST " +
                "    WHERE COPECREA = ? " +
                "      AND FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "    UNION " +
                "    SELECT DISTINCT TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST_HIST " +
                "    WHERE COPECREA = ? " +
                "      AND FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                ") " +
                "ORDER BY FECHA, OPERACION";
        } else if ("historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    COPECREA AS LEGAJO, " +
                "    TO_CHAR(FCREAREG, 'YYYY-MM-DD') AS FECHA, " +
                "    CDESCRIP AS OPERACION " +
                "FROM ( " +
                "    SELECT DISTINCT COPECREA, TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST " +
                "    WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "      AND COPECREA IS NOT NULL " +
                "    UNION " +
                "    SELECT DISTINCT COPECREA, TRUNC(FCREAREG) AS FCREAREG, CDESCRIP " +
                "    FROM F132HIST_HIST " +
                "    WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD') " +
                "      AND FCREAREG < TO_DATE(?, 'YYYY-MM-DD') + 1 " +
                "      AND CDESCRIP NOT IN ('ENTREGA DE EQUIPO', 'DEVOLUCION DE EQUIPO') " +
                "      AND COPECREA IS NOT NULL " +
                ") " +
                "ORDER BY FECHA, LEGAJO, OPERACION";
        } else if ("rendimiento_online".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH PARAMS AS (SELECT TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS FECHA_DESDE, TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') AS FECHA_HASTA FROM DUAL), " +
                "HIST_SOURCE AS ( " +
                "    SELECT A.FCREAREG, A.CDESCRIP, A.CNUPALET, A.QCANTIDA, A.CREFEREN, A.CNPEDIDO, A.COPECREA, A.CZONADES, A.CZONAORI, A.CALMACEN " +
                "    FROM F132HIST A JOIN PARAMS P ON A.FCREAREG >= P.FECHA_DESDE AND A.FCREAREG <= P.FECHA_HASTA " +
                "    WHERE A.CDESCRIP IN ('Picking', 'TRANSPORTE DE PALETS') " +
                "    UNION ALL " +
                "    SELECT A.FCREAREG, A.CDESCRIP, A.CNUPALET, A.QCANTIDA, A.CREFEREN, A.CNPEDIDO, A.COPECREA, A.CZONADES, A.CZONAORI, A.CALMACEN " +
                "    FROM F132HIST_HIST A JOIN PARAMS P ON A.FCREAREG >= P.FECHA_DESDE AND A.FCREAREG <= P.FECHA_HASTA " +
                "    WHERE A.CDESCRIP IN ('Picking', 'TRANSPORTE DE PALETS') " +
                ") " +
                "SELECT " +
                "    B.CNSECTOR, " +
                "    A.FCREAREG, " +
                "    A.CDESCRIP, " +
                "    A.CNUPALET, " +
                "    A.QCANTIDA, " +
                "    A.CREFEREN, " +
                "    A.CNPEDIDO, " +
                "    A.COPECREA AS LEGAJO, " +
                "    C.NOMBRE, " +
                "    D.DARTICUL AS DARTICUL, " +
                "    A.CZONADES AS DESTINO, " +
                "    SUB1.DESCDIVI AS DIVISION, " +
                "    SYSDATE AS ORACLE_NOW " +
                "FROM HIST_SOURCE A " +
                "JOIN F602ASEC B ON A.CREFEREN = B.CREFEREN AND A.CALMACEN = B.CALMACEN " +
                "LEFT JOIN PV_LEGAJO C ON A.COPECREA = C.LEGAJO " +
                "LEFT JOIN F002ARTI D ON A.CREFEREN = D.CREFEREN " +
                "LEFT JOIN (SELECT DISTINCT CZONALMA, DESCDIVI FROM VW_UBICACIONES_DIVISION) SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("online".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CZONAORI AS ZONA_ORIGEN, " +
                "    A.CUBIORIG AS UBIC_ORIGEN, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.QCANTIDA AS CANTIDAD, " +
                "    A.QPESOREG AS PESO " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("tiempos_muertos".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.FCREAREG AS FH_MOVIMIENTO, " +
                "    A.CNUPALET AS NRO_PALLET, " +
                "    A.CNPEDIDO AS PEDIDO, " +
                "    A.COPECREA, " +
                "    B.NOMBRE AS OPERARIO, " +
                "    UPPER(A.CDESCRIP) AS OPERACION, " +
                "    NVL(SUB1.DESCDIVI, 'SIN MAPEAR') AS ALMACEN " +
                "FROM F132HIST A " +
                "LEFT JOIN PV_LEGAJO B ON A.COPECREA = B.LEGAJO " +
                "LEFT JOIN ( " +
                "    SELECT DISTINCT CZONALMA, DESCDIVI " +
                "    FROM VW_UBICACIONES_DIVISION " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "ORDER BY A.COPECREA, A.FCREAREG";
        } else if ("tnc".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    A.LEGAJO, " +
                "    A.LOTEINFORMACION AS FECHA_INICIO, " +
                "    A.CODIGO AS CODIGO_TNC, " +
                "    B.DESCRIPCION AS DESCRIPCION_TNC, " +
                "    TRUNC(A.TIEMPOMAXIMO / 60) AS MINUTOS_TOPE, " +
                "    CASE " +
                "        WHEN A.ESTADO != 0 THEN A.TIEMPOREAL " +
                "        ELSE ((SYSDATE - A.LOTEINFORMACION) * 86400) " +
                "    END AS TIEMPO_ACUMULADO " +
                "FROM F957ATNC A " +
                "JOIN F956MTNC B " +
                "  ON A.EMPRESA = B.EMPRESA " +
                " AND A.ALMACEN = B.ALMACEN " +
                " AND A.CODIGO = B.CODIGO " +
                "WHERE A.LOTEINFORMACION >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND A.LOTEINFORMACION <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "  AND UPPER(TRIM(B.DESCRIPCION)) <> 'FIN DEL TURNO' " +
                "ORDER BY A.LEGAJO, A.LOTEINFORMACION";
        } else if ("tnc_master".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "    B.CODIGO AS CODIGO_TNC, " +
                "    A.CODIGO AS CODIGO_PRODUCTIVIDAD, " +
                "    B.DESCRIPCION AS DESCRIPCION_TNC, " +
                "    TRUNC(B.DURACION / 60) AS DURACION_MINUTOS_WF, " +
                "    TRUNC(A.TIEMPO_MAXIMO / 60) AS DURACION_MINUTOS_PRODUCTIVIDAD, " +
                "    A.TIENE_TIEMPO_MAXIMO, " +
                "    A.TIENE_TOLERANCIA_X_EXCESO, " +
                "    TRUNC(A.TOLERANCIA_X_EXCESO / 60) AS TOLERANCIA_X_EXCESO, " +
                "    A.CANTIDAD_DE_OCURRENCIAS, " +
                "    B.REQUIEREAUTORIZACION, " +
                "    B.TIPOTNC " +
                "FROM F956MTNC B " +
                "LEFT JOIN PV_FUNCION A " +
                "  ON REGEXP_LIKE(A.CODIGO, '^RF-TNC-[0-9]+$') " +
                " AND TO_NUMBER(REPLACE(A.CODIGO, 'RF-TNC-', '')) = B.CODIGO " +
                "ORDER BY B.CODIGO";
        } else if ("tnc_monitor".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH BASE AS ( " +
                "    SELECT " +
                "        A.EMPRESA, " +
                "        A.ALMACEN, " +
                "        A.LEGAJO, " +
                "        A.CODIGO AS CODIGO_TNC, " +
                "        A.LOTEINFORMACION, " +
                "        A.ULTIMAMODIFICACION, " +
                "        TO_CHAR(A.LOTEINFORMACION, 'YYYY-MM-DD') AS DIA_TNC, " +
                "        B.DESCRIPCION AS TNC, " +
                "        A.ESTADO, " +
                "        TRUNC( " +
                "            CASE " +
                "                WHEN A.ESTADO <> 0 THEN A.TIEMPOREAL / 60 " +
                "                ELSE (SYSDATE - A.LOTEINFORMACION) * 1440 " +
                "            END " +
                "        ) AS MINUTOS_CONSUMIDOS, " +
                "        TRUNC(A.TIEMPOMAXIMO / 60) AS MINUTOS_TOPE " +
                "    FROM F957ATNC A " +
                "    JOIN F956MTNC B " +
                "      ON A.EMPRESA = B.EMPRESA " +
                "     AND A.ALMACEN = B.ALMACEN " +
                "     AND A.CODIGO = B.CODIGO " +
                "    WHERE A.LOTEINFORMACION >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "      AND A.LOTEINFORMACION < TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "      AND A.CODIGO <> 62 " +
                "      AND UPPER(TRIM(B.DESCRIPCION)) <> 'FIN DEL TURNO' " +
                ") " +
                "SELECT " +
                "    A.EMPRESA, " +
                "    A.ALMACEN, " +
                "    A.LEGAJO, " +
                "    C.NOMBRE AS OPERARIO, " +
                "    C.AREA_PERS_TXT AS AREA, " +
                "    C.PUESTO AS PUESTO, " +
                "    C.FOTO AS FOTO, " +
                "    A.CODIGO_TNC, " +
                "    A.DIA_TNC, " +
                "    TO_CHAR(LOTEINFORMACION, 'YYYY-MM-DD HH24:MI:SS') AS LOTEINFORMACION_TS, " +
                "    TO_CHAR(ULTIMAMODIFICACION, 'YYYY-MM-DD HH24:MI:SS') AS ULTIMAMODIFICACION_TS, " +
                "    TO_CHAR(LOTEINFORMACION, 'HH24:MI:SS') AS INICIO, " +
                "    CASE " +
                "        WHEN ESTADO = 0 THEN NULL " +
                "        WHEN ULTIMAMODIFICACION = LOTEINFORMACION THEN NULL " +
                "        ELSE TO_CHAR(ULTIMAMODIFICACION, 'HH24:MI:SS') " +
                "    END AS FIN, " +
                "    TNC, " +
                "    CASE " +
                "        WHEN ESTADO = 0 THEN 'Activo' " +
                "        ELSE 'Finalizado' " +
                "    END AS ESTADO, " +
                "    MINUTOS_CONSUMIDOS AS MINUTOS, " +
                "    MINUTOS_TOPE AS TOPE, " +
                "    MINUTOS_CONSUMIDOS - MINUTOS_TOPE AS DIFERENCIA, " +
                "    CASE " +
                "        WHEN MINUTOS_CONSUMIDOS <= MINUTOS_TOPE OR MINUTOS_TOPE = 0 THEN 'Dentro de tope' " +
                "        ELSE 'Excedido' " +
                "    END AS ESTADO_TIEMPO " +
                "FROM BASE A " +
                "LEFT JOIN ( " +
                "    SELECT " +
                "        CASE " +
                "            WHEN REGEXP_LIKE(TRIM(LEGAJO), '^[0-9]+$') THEN TO_NUMBER(TRIM(LEGAJO)) " +
                "        END AS LEGAJO_NUM, " +
                "        NOMBRE, " +
                "        AREA_PERS_TXT, " +
                "        PUESTO, " +
                "        FOTO " +
                "    FROM WF_ACTIVE_EMPLOYEE " +
                ") C ON A.LEGAJO = C.LEGAJO_NUM " +
                "ORDER BY LOTEINFORMACION DESC";
        } else if ("plantel".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "A.FCREAREG AS FHMovimiento, " +
                "A.COPECREA AS Operario, " +
                "A.QCANTIDA AS Cantidad, " +
                "A.CZONAORI AS ZonaOrigen, " +
                "A.CNUPALET AS NroPallet, " +
                "A.QPESOREG AS PesoRegistrado, " +
                "SUB1.DESCDIVI AS Almacen " +
                "FROM F132HIST A " +
                "JOIN ( " +
                "  SELECT DISTINCT CZONALMA, DESCDIVI " +
                "  FROM VW_UBICACIONES_DIVISION " +
                "  WHERE DESCDIVI IN ('SECTOR SECOS', 'VARIOS NO ALIMENTOS') " +
                ") SUB1 ON SUB1.CZONALMA = A.CZONAORI " +
                "WHERE A.FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND A.FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND A.CDESCRIP = 'Picking' " +
                "ORDER BY A.FCREAREG";
        } else if ("picking_ubicaciones_hist".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH UBICS AS ( " +
                "  SELECT CUBIORIG " +
                "  FROM F132HIST_HIST A " +
                "  WHERE UPPER(CDESCRIP) = 'PICKING' " +
                "    AND CUBIORIG IS NOT NULL " +
                ") " +
                "SELECT DISTINCT CUBIORIG AS UBICACION_CODIGO " +
                "FROM UBICS " +
                "ORDER BY CUBIORIG";
        } else if ("rack_stock".equalsIgnoreCase(queryKey)) {
            String[] ubicaciones = splitList(nivelArg);
            StringBuilder like = new StringBuilder();
            for (int i = 0; i < ubicaciones.length; i++) {
                if (i > 0) like.append(" OR ");
                like.append("F005.CHUECOPA LIKE ?");
            }
            if (ubicaciones.length == 0) {
                like.append("1 = 0");
            }
            sql =
                "WITH POSICIONES AS ( " +
                "SELECT F005.*, F605.XTIPUBIC, F605.CPASLOGI, F605.CHUELOGI, F605.CDIGLOGI " +
                "FROM F005UBIA F005 JOIN F605RUFL F605 ON F605.CZONALMA = F005.CZONALMA " +
                "AND F605.CPASILLO = F005.CPASILLO " +
                "AND F605.CHUECOPA = F005.CHUECOPA " +
                "WHERE F005.CEMPRESA = 1 " +
                "AND F005.CALMACEN = 93 " +
                "AND F005.CZONALMA = ? " +
                "AND F005.CPASILLO = ? " +
                "AND (" + like.toString() + ") " +
                ") " +
                "SELECT B.CZONALMA, B.CPASILLO, B.CHUECOPA, A.CNUPALET AS PALET, C.DARTICUL AS ARTICULO " +
                "FROM POSICIONES B LEFT JOIN P505STPA A ON B.CZONALMA = A.CZONALMA AND B.CPASILLO = A.CPASILLO AND A.CHUECOPA = B.CHUECOPA " +
                "LEFT JOIN F002ARTI C ON A.CREFEREN = C.CREFEREN " +
                "ORDER BY B.CZONALMA, B.CPASILLO, B.CHUECOPA, A.CNUPALET";
        } else if ("rack_inutilizadas".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH base AS ( " +
                "SELECT CZONALMA, CPASILLO, CHUECOPA, QPALALTU, QPALPROF, XSITUBIC, CODINUTI " +
                "FROM F005UBIA " +
                "WHERE XSITUBIC = 'I' AND CODINUTI = '1' " +
                "), hist_rank AS ( " +
                "SELECT ROW_NUMBER() OVER ( " +
                "PARTITION BY h.CZONALMA, h.CPASILLO, h.CHUECOPA, h.CODINUTI " +
                "ORDER BY h.FCREAREG DESC, h.ROWID DESC " +
                ") AS rn, h.* " +
                "FROM F671HMIH h INNER JOIN base b " +
                "ON h.CZONALMA = b.CZONALMA " +
                "AND h.CPASILLO = b.CPASILLO " +
                "AND h.CHUECOPA = b.CHUECOPA " +
                "AND h.CODINUTI = b.CODINUTI " +
                ") " +
                "SELECT b.CZONALMA, b.CPASILLO, b.CHUECOPA, b.QPALALTU, " +
                "h.FCREAREG, h.USUACREA, h.MOVIMIEN, h.OBSERVAC " +
                "FROM base b LEFT JOIN hist_rank h " +
                "ON h.CZONALMA = b.CZONALMA " +
                "AND h.CPASILLO = b.CPASILLO " +
                "AND h.CHUECOPA = b.CHUECOPA " +
                "AND h.CODINUTI = b.CODINUTI " +
                "AND h.rn = 1 " +
                "ORDER BY h.FCREAREG";
        } else if ("stock_cd".equalsIgnoreCase(queryKey)) {
            sql =
                "SELECT " +
                "F002.CREFEREN REFERENCIA, " +
                "SUM(P505.QSTKFISI * F209.QCOECONV) AS UNIDADES " +
                "FROM F002ARTI F002 JOIN P505STPA P505 ON P505.CREFEREN = F002.CREFEREN " +
                "JOIN F209CONV F209 ON F209.CREFEREN = P505.CREFEREN AND F209.CVARLOGI = P505.CVARLOGI " +
                "AND F209.CEMPRESA = P505.CEMPRESA " +
                "AND F209.CCONSIGN = P505.CCONSIGN " +
                "AND F209.CPRESENT = P505.CPRESENT " +
                "WHERE F002.CEMPRESA = '1' " +
                "AND F002.DDEPARTA IN (84) " +
                "AND F209.CVARLODP = '0' " +
                "AND F209.CEMPRESA = P505.CEMPRESA " +
                "GROUP BY " +
                "F002.CREFEREN";
        } else {
            sql =
                "SELECT " +
                "FCREAREG AS FHMovimiento, " +
                "CTIPTRAB AS TipoTrabajo, " +
                "CNUPALET AS NroPallet, " +
                "QCANTIDA AS Cantidad, " +
                "CREFEREN AS Referencia, " +
                "CZONAORI AS ZonaOrigen, " +
                "CUBIORIG AS UbicOrige, " +
                "COPECREA AS Operario, " +
                "QPESOREG AS PesoRegistrado " +
                "FROM F132HIST " +
                "WHERE FCREAREG >= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND FCREAREG <= TO_DATE(?, 'YYYY-MM-DD HH24:MI:SS') " +
                "AND CDESCRIP = 'Picking' " +
                "ORDER BY FCREAREG";
        }

        Class.forName("oracle.jdbc.OracleDriver");

        try (
            Connection conn = DriverManager.getConnection(jdbcUrl, user, password);
            PreparedStatement ps = conn.prepareStatement(sql)
        ) {
            if ("premio_escala".equalsIgnoreCase(queryKey)) {
                ps.setString(1, grupoFuncionesArg);
            } else if ("premio_pago_actual".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaDesde);
                ps.setString(2, operacionArg);
                ps.setString(3, nivelArg);
                String[] legajos = splitList(legajo);
                for (int i = 0; i < legajos.length; i++) {
                    ps.setString(4 + i, legajos[i]);
                }
            } else if ("premio_produccion_hora".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg);
                ps.setString(2, fechaDesde);
                ps.setString(3, fechaHasta);
                String[] legajos = splitList(legajo);
                for (int i = 0; i < legajos.length; i++) {
                    ps.setString(4 + i, legajos[i]);
                }
                ps.setString(4 + legajos.length, operacionArg);
            } else if ("pp_premio_escalas".equalsIgnoreCase(queryKey)) {
                ps.setString(1, operacionArg);
            } else if ("pp_premio_escalas_por_id".equalsIgnoreCase(queryKey)) {
                ps.setString(1, operacionArg);
                ps.setString(2, grupoFuncionesArg);
            } else if ("pp_premio_etapas_hora".equalsIgnoreCase(queryKey) || "pp_premio_liquidacion_dia".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, operacionArg);
            } else if ("pp_premio_etapas_hora_por_id".equalsIgnoreCase(queryKey) || "pp_premio_liquidacion_dia_por_id".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, operacionArg);
                ps.setString(3, grupoFuncionesArg);
            } else if ("pv_etapas_desc_funcion_dia".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
            } else if ("pv_etapas_funciones_operacion_dia".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, operacionArg);
            } else if ("pv_liquidacion_grupo_dia".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, grupoFuncionesArg);
            } else if ("premio_caso_modelo_final".equalsIgnoreCase(queryKey)) {
                ps.setString(1, grupoFuncionesArg);
                ps.setString(2, fechaOperativaArg);
                ps.setString(3, fechaDesde);
                ps.setString(4, fechaHasta);
                String[] legajos = splitList(legajo);
                for (int i = 0; i < legajos.length; i++) {
                    ps.setString(5 + i, legajos[i]);
                }
                int offset = 5 + legajos.length;
                ps.setString(offset, operacionArg);
                ps.setString(offset + 1, fechaOperativaArg);
                ps.setString(offset + 2, operacionArg);
                for (int i = 0; i < legajos.length; i++) {
                    ps.setString(offset + 3 + i, legajos[i]);
                }
            } else if ("premio_caso_modelo_rango".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, operacionArg);
                ps.setString(3, almacenArg);
            } else if ("premio_caso_modelo_detalle".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaOperativaArg.replace("-", "/"));
                ps.setString(2, operacionArg);
                ps.setString(3, almacenArg);
                ps.setString(4, legajoDetalleArg);
            } else if ("daily_productividad_raw".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaDesde);
                ps.setString(2, fechaHasta);
                ps.setString(3, fechaDesde);
                ps.setString(4, fechaHasta);
            } else if ("rack_stock".equalsIgnoreCase(queryKey)) {
                ps.setString(1, legajo);
                ps.setString(2, operacionArg);
                String[] ubicaciones = splitList(nivelArg);
                for (int i = 0; i < ubicaciones.length; i++) {
                    ps.setString(3 + i, ubicaciones[i] + "%");
                }
            } else if (!"monitor_cargas".equalsIgnoreCase(queryKey) && !"picking_ubicaciones_hist".equalsIgnoreCase(queryKey) && !"tnc_master".equalsIgnoreCase(queryKey) && !"stock_cd".equalsIgnoreCase(queryKey) && !"rack_inutilizadas".equalsIgnoreCase(queryKey) && !"pv_grupo_funciones_catalogo".equalsIgnoreCase(queryKey) && !"rend_premio_escalas".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaDesde);
                ps.setString(2, fechaHasta);
                if ("gestion_productividad_picking".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, fechaDesde);
                    ps.setString(4, fechaHasta);
                } else if ("historia_productividad_legajo".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, legajo);
                } else if ("historia_tnc_legajo".equalsIgnoreCase(queryKey)) {
                    ps.setString(1, legajo);
                    ps.setString(2, fechaDesde);
                    ps.setString(3, fechaHasta);
                } else if ("historia_actividad_operaciones".equalsIgnoreCase(queryKey)) {
                    ps.setString(1, legajo);
                    ps.setString(2, fechaDesde);
                    ps.setString(3, fechaHasta);
                    ps.setString(4, legajo);
                    ps.setString(5, fechaDesde);
                    ps.setString(6, fechaHasta);
                } else if ("historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey)) {
                    ps.setString(3, fechaDesde);
                    ps.setString(4, fechaHasta);
                }
            }

            try (ResultSet rs = ps.executeQuery()) {
                StringBuilder out = new StringBuilder();
                out.append("[");
                boolean first = true;
                while (rs.next()) {
                    if (!first) out.append(",");
                    first = false;

                    if ("monitor_cargas".equalsIgnoreCase(queryKey) || "premio_escala".equalsIgnoreCase(queryKey) || "premio_pago_actual".equalsIgnoreCase(queryKey) || "premio_produccion_hora".equalsIgnoreCase(queryKey) || "pp_premio_escalas".equalsIgnoreCase(queryKey) || "pp_premio_escalas_por_id".equalsIgnoreCase(queryKey) || "pp_premio_etapas_hora".equalsIgnoreCase(queryKey) || "pp_premio_etapas_hora_por_id".equalsIgnoreCase(queryKey) || "pp_premio_liquidacion_dia".equalsIgnoreCase(queryKey) || "pp_premio_liquidacion_dia_por_id".equalsIgnoreCase(queryKey) || "pp_estudio_premios_oracle".equalsIgnoreCase(queryKey) || "pv_grupo_funciones_catalogo".equalsIgnoreCase(queryKey) || "pv_etapas_desc_funcion_dia".equalsIgnoreCase(queryKey) || "pv_etapas_funciones_operacion_dia".equalsIgnoreCase(queryKey) || "pv_liquidacion_grupo_dia".equalsIgnoreCase(queryKey) || "premio_caso_modelo_final".equalsIgnoreCase(queryKey) || "premio_caso_modelo_rango".equalsIgnoreCase(queryKey) || "premio_caso_modelo_detalle".equalsIgnoreCase(queryKey) || "rendimiento_online".equalsIgnoreCase(queryKey) || "online".equalsIgnoreCase(queryKey) || "tiempos_muertos".equalsIgnoreCase(queryKey) || "tnc".equalsIgnoreCase(queryKey) || "tnc_master".equalsIgnoreCase(queryKey) || "tnc_monitor".equalsIgnoreCase(queryKey) || "picking_analysis".equalsIgnoreCase(queryKey) || "daily_productividad_raw".equalsIgnoreCase(queryKey) || "daily_picking_real".equalsIgnoreCase(queryKey) || "daily_recepcion_real".equalsIgnoreCase(queryKey) || "daily_despacho_real".equalsIgnoreCase(queryKey) || "daily_despacho_raw".equalsIgnoreCase(queryKey) || "daily_planificacion".equalsIgnoreCase(queryKey) || "daily_picking_plan".equalsIgnoreCase(queryKey) || "daily_despacho_plan".equalsIgnoreCase(queryKey) || "daily_spc_plan".equalsIgnoreCase(queryKey) || "daily_clark_real".equalsIgnoreCase(queryKey) || "plantel_optimo_demanda".equalsIgnoreCase(queryKey) || "picking_ubicaciones_hist".equalsIgnoreCase(queryKey) || "stock_cd".equalsIgnoreCase(queryKey) || "rack_stock".equalsIgnoreCase(queryKey) || "rack_inutilizadas".equalsIgnoreCase(queryKey) || "gestion_productividad_picking".equalsIgnoreCase(queryKey) || "historia_productividad_legajo".equalsIgnoreCase(queryKey) || "historia_productividad_bulk".equalsIgnoreCase(queryKey) || "historia_actividad_operaciones".equalsIgnoreCase(queryKey) || "historia_actividad_operaciones_bulk".equalsIgnoreCase(queryKey) || "rend_premio_dias_pago".equalsIgnoreCase(queryKey) || "rend_premio_escalas".equalsIgnoreCase(queryKey)) {
                        appendGenericJsonRow(rs, out);
                        continue;
                    }

                    Timestamp ts = rs.getTimestamp("FHMOVIMIENTO");
                    String fh = ts == null ? "" : TS_FMT.format(ts.toInstant());

                    out.append("{")
                        .append("\"FHMOVIMIENTO\":\"").append(esc(fh)).append("\",")
                        .append("\"TIPOTRABAJO\":\"").append(esc(hasColumn(rs, "TIPOTRABAJO") ? str(rs.getObject("TIPOTRABAJO")) : "")).append("\",")
                        .append("\"NROPALLET\":\"").append(esc(hasColumn(rs, "NROPALLET") ? str(rs.getObject("NROPALLET")) : "")).append("\",")
                        .append("\"CANTIDAD\":").append(num(rs.getObject("CANTIDAD"))).append(",")
                        .append("\"REFERENCIA\":\"").append(esc(hasColumn(rs, "REFERENCIA") ? str(rs.getObject("REFERENCIA")) : "")).append("\",")
                        .append("\"ZONAORIGEN\":\"").append(esc(hasColumn(rs, "ZONAORIGEN") ? str(rs.getObject("ZONAORIGEN")) : "")).append("\",")
                        .append("\"UBICORIGE\":\"").append(esc(hasColumn(rs, "UBICORIGE") ? str(rs.getObject("UBICORIGE")) : "")).append("\",")
                        .append("\"OPERARIO\":\"").append(esc(str(rs.getObject("OPERARIO")))).append("\",")
                        .append("\"PESOREGISTRADO\":").append(num(rs.getObject("PESOREGISTRADO")));

                    try {
                        if (hasColumn(rs, "ALMACEN")) {
                        out.append(",\"ALMACEN\":\"").append(esc(str(rs.getObject("ALMACEN")))).append("\"");
                        }
                    } catch (Exception ignored) {}

                    out.append("}");
                }
                out.append("]");
                System.out.print(out);
            }
        }
    }
}
