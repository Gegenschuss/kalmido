// 2.46.1 (#1591): "Switch on all modules" under "What do you use Kalmido for?" (Settings > Modules, the purpose dialog,
// the first-run setup). On = every module (the purpose adds its business modules), off = lists and tasks only, whatever
// the purpose. Stored as the setting mods_all (server: purpose_apply / pm_purpose_on); each module stays switchable.
const pm_allOn = () => (S.settings.mods_all ?? '1') !== '0';
const PM_EXTRA_ALL = [...new Set(Object.values(PURPOSE_EXTRA).flat())];
// the modules a purpose switches on with the switch on / off (all null = the purpose's own package, as before 2.46.1)
const pm_purposeOn = (p, all) => new Set(all == null ? PURPOSE_MODS[p] || [] : all ? [...PURPOSE_ALL, ...(PURPOSE_EXTRA[p] || [])] : []);
// the modules the switch itself touches (off also the business modules)
const pm_touched = all => [...PURPOSE_ALL, ...(all === false ? PM_EXTRA_ALL : [])];
function pm_featsWith(all, p = S.settings.purpose || '') {
  const on = pm_purposeOn(p, all), fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
  for (const k of pm_touched(all)) on.has(k) ? fs.add(k) : fs.delete(k);
  for (const k of on) fs.add(k);
  return FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',');
}
const pm_switchHtml = (id, on, label, note) => `<label class="pmsw"><span class="swc"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span><b>${esc(label)}</b>${note ? `<small class="muted">${esc(note)}</small>` : ''}</span></label>`;
const pm_allHtml = (id, on) => pm_switchHtml(id, on, tr('Switch on all modules'), tr('Off: only lists and tasks, no calendar, appointments or contacts. Single modules stay switchable below.'));
// Settings > Modules: the switch applies at once, ONE undo step (modules + the switch together)
document.addEventListener('change', async e => {
  if (e.target.id !== 's-modsall') return;
  const md = e.target.closest('.smodal'), on = e.target.checked;
  await setApply({features: pm_featsWith(on), mods_all: on ? '1' : '0'}, tr('Switch on all modules'));
  if (md) settingsSync();
});
