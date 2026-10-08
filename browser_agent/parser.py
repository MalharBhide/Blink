"""Read DOM accessibility labels; returned text never becomes executable instructions."""

from dataclasses import dataclass, asdict


@dataclass
class Field:
    key: str
    label: str
    kind: str
    required: bool
    options: list[str]
    group: str = ""
    index: int = 0

    def dict(self):
        return asdict(self)


PARSE_JS = r"""() => {
 const elements = [...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]),textarea,select,[role=combobox]')];
 const seen = new Set();
 return elements.filter(el => el.getClientRects().length && !el.disabled).flatMap((el) => {
   if (el.closest('[data-agent-ignore]')) return [];
   const kind = el.getAttribute('role') === 'combobox' ? 'combobox' : (el.type || el.tagName.toLowerCase());
   const group = el.closest('fieldset');
   const legend = group?.querySelector('legend')?.textContent?.trim();
   const linked = el.getAttribute('aria-labelledby')?.split(' ').map(id => document.getElementById(id)?.textContent || '').join(' ');
   const label = ((kind === 'radio' ? legend : '') || el.getAttribute('aria-label') || linked || el.labels?.[0]?.textContent || el.getAttribute('placeholder') || el.name || '').trim();
   if (!label || kind === 'password' || /\b(password|passcode|api key|social security|verification code)\b/i.test(label)) return [];
   const key = el.id || el.name || `agent-field-${elements.indexOf(el)}`;
   const targetKey = kind === 'radio' ? `radio:${el.name}` : key;
   if (seen.has(targetKey)) return [];
   seen.add(targetKey);
   el.setAttribute('data-agent-field', targetKey);
   const radios = kind === 'radio' ? elements.filter(x => x.type === 'radio' && x.name === el.name) : [];
   radios.forEach(x => x.setAttribute('data-agent-field', targetKey));
   const options = kind === 'select-one' || kind === 'select-multiple' ? [...el.options].filter(x=>x.value).map(x=>x.text.trim()) : radios.map(x=>x.labels?.[0]?.textContent?.trim() || x.value);
   const recordGroup = el.closest('[data-record-group]');
   return [{key:targetKey, label:label.replace(/\s*\*\s*$/, ''), kind, required:el.required || el.getAttribute('aria-required') === 'true', options, group:recordGroup?.dataset.recordGroup || '', index:Number(recordGroup?.dataset.recordIndex || 0)}];
 });
}"""


async def parse_form(page):
    fields = [Field(**item) for item in await page.evaluate(PARSE_JS)]
    # Unknown repeating structures must not silently duplicate the first record.
    labels = [item.label.casefold() for item in fields if not item.group]
    repeated = {label for label in labels if labels.count(label) > 1}
    for item in fields:
        if not item.group and item.label.casefold() in repeated:
            item.group = "unclassified_repeat"
    return fields
