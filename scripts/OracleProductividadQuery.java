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

        String sql;
        if ("picking_analysis".equalsIgnoreCase(queryKey)) {
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
                "ORDER BY A.LEGAJO, A.LOTEINFORMACION";
        } else if ("tnc_monitor".equalsIgnoreCase(queryKey)) {
            sql =
                "WITH BASE AS ( " +
                "    SELECT " +
                "        A.LEGAJO, " +
                "        A.LOTEINFORMACION, " +
                "        A.ULTIMAMODIFICACION, " +
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
                ") " +
                "SELECT " +
                "    A.LEGAJO, " +
                "    B.NOMBRE AS OPERARIO, " +
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
                "LEFT JOIN PV_LEGAJO B ON A.LEGAJO = B.LEGAJO " +
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
            if (!"picking_ubicaciones_hist".equalsIgnoreCase(queryKey)) {
                ps.setString(1, fechaDesde);
                ps.setString(2, fechaHasta);
            }

            try (ResultSet rs = ps.executeQuery()) {
                StringBuilder out = new StringBuilder();
                out.append("[");
                boolean first = true;
                while (rs.next()) {
                    if (!first) out.append(",");
                    first = false;

                    if ("online".equalsIgnoreCase(queryKey) || "tiempos_muertos".equalsIgnoreCase(queryKey) || "tnc".equalsIgnoreCase(queryKey) || "tnc_monitor".equalsIgnoreCase(queryKey) || "picking_analysis".equalsIgnoreCase(queryKey) || "picking_ubicaciones_hist".equalsIgnoreCase(queryKey)) {
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
