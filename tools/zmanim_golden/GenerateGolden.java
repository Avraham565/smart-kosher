/*
 * Emits the reference zmanim table that tests/test_zmanim_reference.py
 * checks against.
 *
 * This is the only place KosherJava is ever executed. It runs by hand, its
 * output is committed, and nothing in the product or the test suite needs Java.
 * See README.md for the regeneration command.
 *
 * Every value is seconds from UTC midnight of the row's date, so it can be
 * compared directly against compute_zmanim()'s minutes-from-UTC-midnight
 * without either side knowing about time zones or DST. Values may fall outside
 * [0, 86400): solar midnight lands after it, and that is not an error.
 *
 * The calendar is configured to match what the product computes:
 *   - useElevation(false)      derived zmanim off sea level, which is the
 *                              library default; only sunrise/sunset themselves
 *                              carry the elevation correction
 *   - candleLightingOffset(18) the library default
 */

import com.kosherjava.zmanim.ComplexZmanimCalendar;
import com.kosherjava.zmanim.util.GeoLocation;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.GregorianCalendar;
import java.util.List;
import java.util.TimeZone;

public final class GenerateGolden {

    private static final String[] COLUMNS = {
        "alos_16_1", "misheyakir_11_5", "sunrise_sea", "sunrise_elev",
        "sof_zman_shma_gra", "sof_zman_shma_mga",
        "sof_zman_tfila_gra", "sof_zman_tfila_mga",
        "chatzos", "mincha_gedola", "mincha_gedola_30", "mincha_ketana",
        "plag_hamincha", "sunset_sea", "sunset_elev",
        "tzais_8_5", "tzais_72", "solar_midnight", "candle_18",
    };

    private static final TimeZone UTC = TimeZone.getTimeZone("UTC");

    private static final class City {
        final String id;
        final double lat;
        final double lon;
        final double elevation;

        City(String id, double lat, double lon, double elevation) {
            this.id = id;
            this.lat = lat;
            this.lon = lon;
            this.elevation = elevation;
        }
    }

    public static void main(String[] args) throws IOException {
        if (args.length != 4) {
            System.err.println("usage: GenerateGolden <cities.tsv> <startYear> <endYear> <out.csv>");
            System.exit(2);
        }
        List<City> cities = readCities(args[0]);
        int startYear = Integer.parseInt(args[1]);
        int endYear = Integer.parseInt(args[2]);

        long rows = 0;
        try (BufferedWriter out = Files.newBufferedWriter(Paths.get(args[3]), StandardCharsets.UTF_8)) {
            out.write("city,date," + String.join(",", COLUMNS));
            out.newLine();
            for (City city : cities) {
                GeoLocation location = new GeoLocation(city.id, city.lat, city.lon, city.elevation, UTC);
                Calendar cursor = new GregorianCalendar(UTC);
                cursor.clear();
                cursor.set(startYear, Calendar.JANUARY, 1);
                while (cursor.get(Calendar.YEAR) <= endYear) {
                    out.write(row(location, city.id, cursor));
                    out.newLine();
                    rows++;
                    cursor.add(Calendar.DAY_OF_MONTH, 1);
                }
            }
        }
        System.err.printf("wrote %d rows for %d cities (%d-%d)%n",
                rows, cities.size(), startYear, endYear);
    }

    private static String row(GeoLocation location, String cityId, Calendar day) {
        ComplexZmanimCalendar cal = new ComplexZmanimCalendar(location);
        cal.setUseElevation(false);
        cal.setCandleLightingOffset(18);
        cal.getCalendar().clear();
        cal.getCalendar().setTimeZone(UTC);
        cal.getCalendar().set(day.get(Calendar.YEAR), day.get(Calendar.MONTH), day.get(Calendar.DAY_OF_MONTH));

        Date[] values = {
            cal.getAlos16Point1Degrees(),
            cal.getMisheyakir11Point5Degrees(),
            cal.getSeaLevelSunrise(),
            cal.getSunrise(),
            cal.getSofZmanShmaGRA(),
            cal.getSofZmanShmaMGA(),
            cal.getSofZmanTfilaGRA(),
            cal.getSofZmanTfilaMGA(),
            cal.getChatzos(),
            cal.getMinchaGedola(),
            cal.getMinchaGedola30Minutes(),
            cal.getMinchaKetana(),
            cal.getPlagHamincha(),
            cal.getSeaLevelSunset(),
            cal.getSunset(),
            cal.getTzais(),
            cal.getTzais72(),
            cal.getSolarMidnight(),
            cal.getCandleLighting(),
        };

        long midnight = day.getTimeInMillis();
        StringBuilder line = new StringBuilder(320);
        line.append(cityId).append(',').append(isoDate(day));
        for (Date value : values) {
            line.append(',');
            if (value != null) {
                // Tenths of a second. The suite asserts agreement to within a
                // second, so a 0.05 s rounding floor is far below anything it
                // can rule on, and full millisecond precision tripled the size
                // of the committed file for no reachable benefit.
                line.append(String.format("%.1f", (value.getTime() - midnight) / 1000.0));
            }
        }
        return line.toString();
    }

    private static String isoDate(Calendar day) {
        return String.format("%04d-%02d-%02d",
                day.get(Calendar.YEAR), day.get(Calendar.MONTH) + 1, day.get(Calendar.DAY_OF_MONTH));
    }

    private static List<City> readCities(String path) throws IOException {
        List<City> cities = new ArrayList<>();
        try (BufferedReader reader = Files.newBufferedReader(Paths.get(path), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isEmpty()) {
                    continue;
                }
                String[] parts = line.split("\t");
                cities.add(new City(parts[0], Double.parseDouble(parts[1]),
                        Double.parseDouble(parts[2]), Double.parseDouble(parts[3])));
            }
        }
        return cities;
    }
}
