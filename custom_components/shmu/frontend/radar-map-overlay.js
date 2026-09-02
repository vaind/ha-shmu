/**
 * SHMÚ radar overlay — a plugin for the ha-map-card Lovelace card
 * (https://github.com/nathan-gs/ha-map-card).
 *
 * It drapes one of this integration's `image.*_radar_map*` entities over the
 * card's Leaflet map, so the radar can be panned and zoomed instead of being
 * a fixed-size picture. Those entities render the whole national composite at
 * its native resolution with nothing drawn on it, and publish the WGS84 box
 * they cover as `bbox_south` / `bbox_west` / `bbox_north` / `bbox_east`. Both
 * the composite grid and a web map are spherical Mercator, so an image
 * overlay stretched between those corners lines up with the ground exactly.
 *
 * The integration serves this file itself, so it needs no HACS download and
 * no Lovelace resource — the map card imports a plugin straight from its URL:
 *
 * ```yaml
 * type: custom:map-card
 * focus_entity: zone.home   # centre on your Home Assistant location
 * zoom: 8
 * plugins:
 *   - name: shmu-radar
 *     url: /shmu_static/radar-map-overlay.js
 *     options:
 *       entity: image.hurbanovo_radar_map_loop
 *       opacity: 0.6
 * ```
 *
 * Options: `entity` (required) is any SHMÚ radar map image entity — the loop
 * animates on its own, `..._radar_map` is a single still frame, and
 * `..._radar_map_frame` follows the "Radar frame" slider. `opacity` and
 * `attribution` are optional.
 *
 * Data © Slovenský hydrometeorologický ústav (SHMÚ), CC BY 4.0.
 */

/** Reflectivity hides the basemap if drawn solid; let the terrain through. */
const DEFAULT_OPACITY = 0.6;

/** SHMÚ data is CC BY 4.0: credit it on the map that displays it. */
const DEFAULT_ATTRIBUTION =
  'Radar © <a href="https://opendata.shmu.sk/" target="_blank" rel="noreferrer noopener">SHMÚ</a>';

/** States that mean "no picture right now", as opposed to a broken config. */
const NO_PICTURE = new Set(["unavailable", "unknown"]);

export default function (L, PluginBase, Logger) {
  return class ShmuRadarOverlay extends PluginBase {
    constructor(map, name, options = {}) {
      super(map, name, options);
      this.entityId = options.entity;
      const opacity = Number(options.opacity);
      this.opacity = Number.isFinite(opacity) ? opacity : DEFAULT_OPACITY;
      this.attribution = options.attribution ?? DEFAULT_ATTRIBUTION;
      this.layer = null;
      // What the layer currently shows, so a repaint only happens on a real
      // change: update() runs on every Home Assistant state change.
      this.frameId = null;
      this.bounds = null;
      // Last problem reported, to keep that same cadence from spamming the log.
      this.complaint = null;
    }

    async init() {
      if (!this.entityId) {
        Logger.error(
          `[${this.name}] needs an 'entity' option naming a SHMÚ radar map ` +
            `image entity, e.g. image.<station>_radar_map_loop`,
        );
      }
    }

    async renderMap() {
      this.sync();
    }

    async update() {
      this.sync();
    }

    destroy() {
      this.removeLayer();
    }

    /** Add, move, repaint or hide the overlay to match the entity. */
    sync() {
      if (!this.entityId) return;
      const frame = this.currentFrame();
      if (frame === null) {
        this.removeLayer();
        return;
      }
      if (this.layer === null) {
        this.layer = L.imageOverlay(frame.url, frame.bounds, {
          opacity: this.opacity,
          attribution: this.attribution,
          alt: "SHMÚ radar reflectivity",
        }).addTo(this.map);
        Logger.debug(`[${this.name}] overlay added for ${this.entityId}`);
      } else {
        if (this.bounds === null || !frame.bounds.equals(this.bounds)) {
          this.layer.setBounds(frame.bounds);
        }
        if (frame.id !== this.frameId) {
          this.layer.setUrl(frame.url);
        }
      }
      this.frameId = frame.id;
      this.bounds = frame.bounds;
      this.complaint = null;
    }

    /** The picture to show and where it belongs, or null if there is none. */
    currentFrame() {
      const hass = document.querySelector("home-assistant")?.hass;
      if (!hass) return null;
      const state = hass.states[this.entityId];
      if (!state) {
        this.complain(`entity ${this.entityId} does not exist`);
        return null;
      }
      // A radar dropout is transient and already visible elsewhere; drop the
      // overlay quietly and pick it up again when a frame arrives.
      if (NO_PICTURE.has(state.state)) return null;

      const attrs = state.attributes ?? {};
      const box = [
        attrs.bbox_south,
        attrs.bbox_west,
        attrs.bbox_north,
        attrs.bbox_east,
      ];
      if (!attrs.entity_picture || box.some((v) => typeof v !== "number")) {
        this.complain(
          `entity ${this.entityId} has no picture with a bounding box — ` +
            `point this plugin at one of the *_radar_map* image entities`,
        );
        return null;
      }

      const [south, west, north, east] = box;
      // The entity's state is the frame's valid time, which makes it both the
      // frame's identity and the cache-buster the URL needs: the access token
      // in entity_picture rotates on its own schedule, so a browser reusing a
      // cached response would otherwise keep showing an old frame.
      //
      // Identity is the state alone, never the whole URL. Home Assistant
      // rotates that token every five minutes and writes a new state for it,
      // so repainting on a URL change would re-download the picture (~330 KB
      // for a loop) and restart the animation for nothing. Keeping the applied
      // URL is safe: Home Assistant still accepts the previous token, and
      // every path that rebuilds the layer reads the current one anyway.
      const separator = attrs.entity_picture.includes("?") ? "&" : "?";
      return {
        id: state.state,
        url: `${attrs.entity_picture}${separator}shmu_frame=${encodeURIComponent(
          state.state,
        )}`,
        bounds: L.latLngBounds([south, west], [north, east]),
      };
    }

    removeLayer() {
      if (this.layer !== null) {
        this.layer.remove();
        this.layer = null;
        this.frameId = null;
        this.bounds = null;
      }
    }

    /** Log a problem once, not on every state change that re-runs update(). */
    complain(message) {
      if (this.complaint === message) return;
      this.complaint = message;
      Logger.warn(`[${this.name}] ${message}`);
    }
  };
}
