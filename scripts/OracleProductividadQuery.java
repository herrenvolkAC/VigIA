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

    public static void main(String[] args) throws Exception {
        if (args.length < 5) {
            System.err.println("Uso: OracleProductividadQuery <jdbcUrl> <user> <password> <fechaDesde> <fechaHasta>");
            System.exit(2);
        }

        String jdbcUrl = args[0];
        String user = args[1];
        String password = args[2];
        String fechaDesde = args[3];
        String fechaHasta = args[4];

        String sql =
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

        Class.forName("oracle.jdbc.OracleDriver");

        try (
            Connection conn = DriverManager.getConnection(jdbcUrl, user, password);
            PreparedStatement ps = conn.prepareStatement(sql)
        ) {
            ps.setString(1, fechaDesde);
            ps.setString(2, fechaHasta);

            try (ResultSet rs = ps.executeQuery()) {
                StringBuilder out = new StringBuilder();
                out.append("[");
                boolean first = true;
                while (rs.next()) {
                    if (!first) out.append(",");
                    first = false;

                    Timestamp ts = rs.getTimestamp("FHMOVIMIENTO");
                    String fh = ts == null ? "" : TS_FMT.format(ts.toInstant());

                    out.append("{")
                        .append("\"FHMOVIMIENTO\":\"").append(esc(fh)).append("\",")
                        .append("\"TIPOTRABAJO\":\"").append(esc(str(rs.getObject("TIPOTRABAJO")))).append("\",")
                        .append("\"NROPALLET\":\"").append(esc(str(rs.getObject("NROPALLET")))).append("\",")
                        .append("\"CANTIDAD\":").append(num(rs.getObject("CANTIDAD"))).append(",")
                        .append("\"REFERENCIA\":\"").append(esc(str(rs.getObject("REFERENCIA")))).append("\",")
                        .append("\"ZONAORIGEN\":\"").append(esc(str(rs.getObject("ZONAORIGEN")))).append("\",")
                        .append("\"UBICORIGE\":\"").append(esc(str(rs.getObject("UBICORIGE")))).append("\",")
                        .append("\"OPERARIO\":\"").append(esc(str(rs.getObject("OPERARIO")))).append("\",")
                        .append("\"PESOREGISTRADO\":").append(num(rs.getObject("PESOREGISTRADO")))
                        .append("}");
                }
                out.append("]");
                System.out.print(out);
            }
        }
    }
}
