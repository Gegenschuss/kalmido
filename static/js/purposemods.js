// 2.46.1 (#1591): "Switch on all modules" under "What do you use Kalmido for?" (Settings > Modules, the purpose dialog,
// the first-run setup). On = every module (the purpose adds its business modules), off = lists and tasks only, whatever
// the purpose. Stored as the setting mods_all (server: purpose_apply / pm_purpose_on); each module stays switchable.
const pm_allOn = () => (S.settings.mods_all ?? '1') !== '0';
const PM_EXTRA_ALL = [...new Set(Object.values(PURPOSE_EXTRA).flat())];
// the modules a purpose switches on with the switch on / off (all null = the purpose's own package, as before 2.46.1)
// 2.56.1 (#1808): "all on" = every module of Settings > Modules (FEATS), minus what the instance switched off (server: pma_full)
const pma_full = () => FEATS.map(x => x[0]).filter(k => !(k === 'collab' && S.collabAll === false) && !(k === 'time' && S.timeAll === false));
const pm_purposeOn = (p, all) => new Set(all == null ? PURPOSE_MODS[p] || [] : all ? pma_full() : []);
// 2.171.0 (#2676): the switch in Settings > Modules shows on only while every module really is on (mods_all stays the
// stored choice the purpose uses); switching it on turns on every module, the parts of the areas too (pm_featsWith)
const pm_allShown = () => pma_full().every(k => feat(k));
// the modules the switch itself touches (off also the business modules)
const pm_touched = all => all ? pma_full() : all === false ? FEATS.map(x => x[0]) : [...PURPOSE_ALL];  // 2.56.1 (#1808): off = lists and tasks only, every module off
function pm_featsWith(all, p = S.settings.purpose || '') {
  const on = pm_purposeOn(p, all), fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
  for (const k of pm_touched(all)) on.has(k) ? fs.add(k) : fs.delete(k);
  for (const k of on) fs.add(k);
  return FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',');
}
const pm_switchHtml = (id, on, label, note) => `<label class="pmsw"><span class="swc"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${esc(label)}</b>${note ? `<small class="muted">${esc(note)}</small>` : ''}</span></label>`;
const pm_allHtml = (id, on) => pm_switchHtml(id, on, tr('Switch on all modules'), tr('Off: only projects and tasks, no calendar, appointments or contacts. Single modules stay switchable below.'));
// Settings > Modules: the switch applies at once, ONE undo step (modules + the switch together)
document.addEventListener('change', async e => {
  if (e.target.id !== 's-modsall') return;
  const md = e.target.closest('.smodal'), on = e.target.checked;
  await setApply({features: pm_featsWith(on), mods_all: on ? '1' : '0'}, tr('Switch on all modules'));
  if (md) settingsSync();
});
