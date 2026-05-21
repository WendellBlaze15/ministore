/**
 * Philippine Address cascading dropdowns (Region → Province → City → Barangay).
 *
 * Data source: PSGC API (https://psgc.gitlab.io/api/) — free, no auth, official PSA codes.
 *
 * - Uses our Flask proxy (/api/ph-address/...) to avoid CORS surprises and keep
 *   any future caching server-side.
 * - Falls back to the upstream URL if the proxy ever returns non-OK.
 * - Submits human-readable names (not codes) so they land directly in profiles.
 */
(function () {
  const BASE_LOCAL = '/api/ph-address';
  const BASE_REMOTE = 'https://psgc.gitlab.io/api';

  const $region    = document.querySelector('[data-ph="region"]');
  const $province  = document.querySelector('[data-ph="province"]');
  const $city      = document.querySelector('[data-ph="city"]');
  const $barangay  = document.querySelector('[data-ph="barangay"]');
  if (!$region || !$province || !$city || !$barangay) return;

  async function fetchJson(path) {
    try {
      const res = await fetch(`${BASE_LOCAL}${path}`);
      if (res.ok) return res.json();
    } catch (_) { /* fall through */ }
    const res = await fetch(`${BASE_REMOTE}${path}`);
    if (!res.ok) throw new Error(`PSGC ${path} -> ${res.status}`);
    return res.json();
  }

  function reset(sel, placeholder) {
    sel.innerHTML = '';
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = placeholder;
    sel.appendChild(opt);
    sel.disabled = false;
  }

  function fill(sel, rows, labelKey = 'name') {
    rows
      .slice()
      .sort((a, b) => a[labelKey].localeCompare(b[labelKey]))
      .forEach((row) => {
        const o = document.createElement('option');
        o.value = row[labelKey];
        o.dataset.code = row.code;
        o.textContent = row[labelKey];
        sel.appendChild(o);
      });
  }

  async function loadRegions() {
    reset($region, 'Loading…'); $region.disabled = true;
    try {
      const data = await fetchJson('/regions/');
      reset($region, 'Select region…');
      fill($region, data);
    } catch (e) {
      reset($region, "Couldn't load regions — fill in manually below");
      console.warn('PSGC error:', e);
    }
  }

  async function loadProvinces(regionCode) {
    reset($province, 'Loading…'); $province.disabled = true;
    reset($city, 'Select province first'); $city.disabled = true;
    reset($barangay, 'Select city first'); $barangay.disabled = true;
    try {
      const data = await fetchJson(`/regions/${regionCode}/provinces/`);
      // NCR has no provinces — fall back to cities-municipalities directly.
      if (!data.length) {
        reset($province, '— (no provinces in this region) —');
        $province.disabled = true;
        await loadCities(regionCode, /*useRegion=*/true);
        return;
      }
      reset($province, 'Select province…');
      fill($province, data);
    } catch (e) {
      reset($province, 'Failed to load provinces');
      console.warn(e);
    }
  }

  async function loadCities(parentCode, useRegion = false) {
    reset($city, 'Loading…'); $city.disabled = true;
    reset($barangay, 'Select city first'); $barangay.disabled = true;
    try {
      const path = useRegion
        ? `/regions/${parentCode}/cities-municipalities/`
        : `/provinces/${parentCode}/cities-municipalities/`;
      const data = await fetchJson(path);
      reset($city, 'Select city / municipality…');
      fill($city, data);
    } catch (e) {
      reset($city, 'Failed to load cities');
      console.warn(e);
    }
  }

  async function loadBarangays(cityCode) {
    reset($barangay, 'Loading…'); $barangay.disabled = true;
    try {
      const data = await fetchJson(`/cities-municipalities/${cityCode}/barangays/`);
      reset($barangay, 'Select barangay…');
      fill($barangay, data);
    } catch (e) {
      reset($barangay, 'Failed to load barangays');
      console.warn(e);
    }
  }

  $region.addEventListener('change', () => {
    const code = $region.selectedOptions[0]?.dataset.code;
    if (!code) {
      reset($province, 'Select region first'); $province.disabled = true;
      reset($city, 'Select province first'); $city.disabled = true;
      reset($barangay, 'Select city first'); $barangay.disabled = true;
      return;
    }
    loadProvinces(code);
  });
  $province.addEventListener('change', () => {
    const code = $province.selectedOptions[0]?.dataset.code;
    if (!code) { reset($city, 'Select province first'); $city.disabled = true; return; }
    loadCities(code, false);
  });
  $city.addEventListener('change', () => {
    const code = $city.selectedOptions[0]?.dataset.code;
    if (!code) { reset($barangay, 'Select city first'); $barangay.disabled = true; return; }
    loadBarangays(code);
  });

  loadRegions();
})();
