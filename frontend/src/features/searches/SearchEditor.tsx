import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
  type SyntheticEvent,
} from "react";

import type {
  ContractType,
  ExperienceLevel,
  SavedSearch,
  SearchCreate,
  SearchUpdate,
  SourceName,
  WorkplaceType,
} from "../../api/types";

type Choice<T extends string> = {
  value: T;
  label: string;
};

const CONTRACT_CHOICES: readonly Choice<ContractType>[] = [
  { value: "cdi", label: "CDI" },
  { value: "cdd", label: "CDD" },
  { value: "interim", label: "Intérim" },
  { value: "stage", label: "Stage" },
  { value: "alternance", label: "Alternance" },
  { value: "freelance", label: "Freelance" },
  { value: "other", label: "Autre" },
];

const WORKPLACE_CHOICES: readonly Choice<WorkplaceType>[] = [
  { value: "on_site", label: "Sur site" },
  { value: "remote", label: "Télétravail" },
  { value: "hybrid", label: "Hybride" },
];

const EXPERIENCE_CHOICES: readonly Choice<ExperienceLevel>[] = [
  { value: "internship", label: "Début de carrière" },
  { value: "junior", label: "Junior" },
  { value: "mid", label: "Intermédiaire" },
  { value: "senior", label: "Senior" },
  { value: "lead", label: "Lead" },
  { value: "director", label: "Direction" },
];

const SOURCE_CHOICES: readonly Choice<SourceName>[] = [
  { value: "freework", label: "Free-Work" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "hellowork", label: "HelloWork" },
  { value: "francetravail", label: "France Travail" },
  { value: "wttj", label: "Welcome to the Jungle" },
  { value: "adzuna", label: "Adzuna" },
];

type EditorValues = {
  name: string;
  keywords: string;
  title: string;
  location: string;
  radiusKm: string;
  contractTypes: ContractType[];
  workplaceTypes: WorkplaceType[];
  experienceLevels: ExperienceLevel[];
  sources: SourceName[];
  active: boolean;
};

type DirtyField = keyof EditorValues;

const EDITOR_FIELDS: readonly DirtyField[] = [
  "name",
  "keywords",
  "title",
  "location",
  "radiusKm",
  "contractTypes",
  "workplaceTypes",
  "experienceLevels",
  "sources",
  "active",
];

type FormErrors = Partial<
  Record<"name" | "keywords" | "location" | "radiusKm" | "sources", string>
>;

type SearchEditorProps = {
  search: SavedSearch | null;
  isSubmitting: boolean;
  submitError: string | null;
  onSubmit: (payload: SearchCreate | SearchUpdate) => Promise<void>;
  onClose: () => void;
};

function allowedValues<T extends string>(
  values: readonly string[],
  choices: readonly Choice<T>[],
): T[] {
  const allowed = new Set(choices.map((choice) => choice.value as string));
  return [...new Set(values.filter((value): value is T => allowed.has(value)))];
}

function initialValues(search: SavedSearch | null): EditorValues {
  if (search === null) {
    return {
      name: "",
      keywords: "",
      title: "",
      location: "France",
      radiusKm: "",
      contractTypes: [],
      workplaceTypes: [],
      experienceLevels: [],
      sources: [],
      active: true,
    };
  }
  return {
    name: search.name,
    keywords: search.keywords.join(", "),
    title: search.title ?? "",
    location: search.location,
    radiusKm: search.radiusKm === null ? "" : String(search.radiusKm),
    contractTypes: allowedValues(search.contractTypes, CONTRACT_CHOICES),
    workplaceTypes: allowedValues(search.workplaceTypes, WORKPLACE_CHOICES),
    experienceLevels: allowedValues(search.experienceLevels, EXPERIENCE_CHOICES),
    sources: allowedValues(search.sources, SOURCE_CHOICES),
    active: search.active,
  };
}

function parseKeywords(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[,;\n]+/)
    .map((keyword) => keyword.trim())
    .filter((keyword) => {
      const key = keyword.toLocaleLowerCase("fr");
      if (!keyword || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
}

function parseRadius(value: string): number | null | undefined {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  if (!/^\d+$/.test(normalized)) {
    return undefined;
  }
  const radius = Number(normalized);
  return Number.isSafeInteger(radius) && radius >= 1 ? radius : undefined;
}

function sameValues(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
}

function ChoiceGroup<T extends string>({
  legend,
  choices,
  selected,
  disabled,
  onToggle,
}: {
  legend: string;
  choices: readonly Choice<T>[];
  selected: readonly T[];
  disabled: boolean;
  onToggle: (value: T, checked: boolean) => void;
}) {
  return (
    <fieldset className="choice-group" disabled={disabled}>
      <legend>{legend}</legend>
      <div className="choice-group__items">
        {choices.map((choice) => (
          <label className="choice-chip" key={choice.value}>
            <input
              type="checkbox"
              value={choice.value}
              checked={selected.includes(choice.value)}
              onChange={(event) => onToggle(choice.value, event.currentTarget.checked)}
            />
            <span>{choice.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function SearchEditor({
  search,
  isSubmitting,
  submitError,
  onSubmit,
  onClose,
}: SearchEditorProps) {
  const [initial] = useState<EditorValues>(() => initialValues(search));
  const [values, setValues] = useState<EditorValues>(initial);
  const [errors, setErrors] = useState<FormErrors>({});
  const dialogRef = useRef<HTMLDialogElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const submitLockRef = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const isEditing = search !== null;

  useEffect(() => {
    const dialog = dialogRef.current;
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (dialog !== null && !dialog.open) {
      try {
        dialog.showModal();
      } catch {
        dialog.setAttribute("open", "");
      }
    }
    nameRef.current?.focus();

    return () => {
      if (dialog?.open) {
        if (typeof dialog.close === "function") {
          dialog.close();
        } else {
          dialog.removeAttribute("open");
        }
      }
      if (returnFocusRef.current?.isConnected) {
        returnFocusRef.current.focus();
      } else {
        document.getElementById("saved-search")?.focus();
      }
    };
  }, []);

  function setTextValue(
    field: "name" | "keywords" | "title" | "location" | "radiusKm",
    value: string,
  ) {
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  }

  function toggleChoice<
    K extends "contractTypes" | "workplaceTypes" | "experienceLevels" | "sources",
  >(field: K, value: EditorValues[K][number], checked: boolean) {
    setValues((current) => {
      const existing = current[field] as string[];
      const next = checked
        ? existing.includes(value) ? existing : [...existing, value]
        : existing.filter((item) => item !== value);
      return { ...current, [field]: next } as EditorValues;
    });
    if (field === "sources") {
      setErrors((current) => ({ ...current, sources: undefined }));
    }
  }

  function isFieldDirty(field: DirtyField): boolean {
    switch (field) {
      case "name":
        return values.name.trim() !== initial.name.trim();
      case "keywords": {
        const current = parseKeywords(values.keywords);
        const original = parseKeywords(initial.keywords);
        return (
          current.length !== original.length ||
          current.some((keyword, index) => keyword !== original[index])
        );
      }
      case "title":
        return (values.title.trim() || null) !== (initial.title.trim() || null);
      case "location":
        return values.location.trim() !== initial.location.trim();
      case "radiusKm":
        return parseRadius(values.radiusKm) !== parseRadius(initial.radiusKm);
      case "contractTypes":
      case "workplaceTypes":
      case "experienceLevels":
      case "sources":
        return !sameValues(values[field], initial[field]);
      case "active":
        return values.active !== initial.active;
    }
  }

  const hasChanges = EDITOR_FIELDS.some(isFieldDirty);

  function requestClose() {
    if (!isSubmitting) {
      onClose();
    }
  }

  function handleCancel(event: SyntheticEvent<HTMLDialogElement>) {
    event.preventDefault();
    requestClose();
  }

  function handleDialogClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) {
      requestClose();
    }
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      requestClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => !element.hasAttribute("hidden"));
    const first = focusable[0];
    const last = focusable.at(-1);
    if (first === undefined) {
      event.preventDefault();
      event.currentTarget.focus();
      return;
    }
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLockRef.current || isSubmitting) {
      return;
    }
    const keywords = parseKeywords(values.keywords);
    const radiusKm = parseRadius(values.radiusKm);
    const nextErrors: FormErrors = {};
    const shouldValidate = (field: DirtyField) =>
      !isEditing || isFieldDirty(field);
    if (shouldValidate("name") && !values.name.trim()) {
      nextErrors.name = "Saisissez un nom pour cette recherche.";
    }
    if (shouldValidate("keywords") && keywords.length === 0) {
      nextErrors.keywords = "Ajoutez au moins un mot-clé.";
    }
    if (shouldValidate("location") && !values.location.trim()) {
      nextErrors.location = "Saisissez un lieu de recherche.";
    }
    if (shouldValidate("radiusKm") && radiusKm === undefined) {
      nextErrors.radiusKm =
        "Le rayon doit être un nombre entier supérieur ou égal à 1.";
    }
    if (
      shouldValidate("sources") &&
      (values.sources.length === 0 ||
        new Set(values.sources).size !== values.sources.length)
    ) {
      nextErrors.sources = "Sélectionnez au moins une source.";
    }
    setErrors(nextErrors);
    const firstError = (
      ["name", "keywords", "location", "radiusKm", "sources"] as const
    ).find((field) => nextErrors[field] !== undefined);
    if (firstError !== undefined) {
      if (firstError === "sources") {
        dialogRef.current
          ?.querySelector<HTMLInputElement>(".choice-group--sources input")
          ?.focus();
      } else {
        const ids = {
          name: "search-name",
          keywords: "search-keywords",
          location: "search-location",
          radiusKm: "search-radius",
        } as const;
        document.getElementById(ids[firstError])?.focus();
      }
      return;
    }

    const title = values.title.trim() || null;
    if (!isEditing) {
      if (radiusKm === undefined) {
        return;
      }
      submitLockRef.current = true;
      try {
        await onSubmit({
          name: values.name.trim(),
          keywords,
          title,
          location: values.location.trim(),
          radiusKm,
          contractTypes: values.contractTypes,
          experienceLevels: values.experienceLevels,
          workplaceTypes: values.workplaceTypes,
          sources: values.sources,
          active: values.active,
        });
      } finally {
        submitLockRef.current = false;
      }
      return;
    }

    if (!hasChanges) {
      return;
    }

    const patch: SearchUpdate = {};
    if (isFieldDirty("name")) patch.name = values.name.trim();
    if (isFieldDirty("keywords")) patch.keywords = keywords;
    if (isFieldDirty("title")) patch.title = title;
    if (isFieldDirty("location")) patch.location = values.location.trim();
    if (isFieldDirty("radiusKm") && radiusKm !== undefined) {
      patch.radiusKm = radiusKm;
    }
    if (isFieldDirty("contractTypes")) {
      patch.contractTypes = values.contractTypes;
    }
    if (isFieldDirty("experienceLevels")) {
      patch.experienceLevels = values.experienceLevels;
    }
    if (isFieldDirty("workplaceTypes")) {
      patch.workplaceTypes = values.workplaceTypes;
    }
    if (isFieldDirty("sources")) patch.sources = values.sources;
    if (isFieldDirty("active")) patch.active = values.active;
    submitLockRef.current = true;
    try {
      await onSubmit(patch);
    } finally {
      submitLockRef.current = false;
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="search-editor"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      aria-modal="true"
      aria-busy={isSubmitting}
      tabIndex={-1}
      onCancel={handleCancel}
      onClick={handleDialogClick}
      onKeyDown={handleDialogKeyDown}
    >
      <div className="search-editor__surface">
        <header className="search-editor__header">
          <div>
            <p className="eyebrow">Recherche enregistrée</p>
            <h2 id={titleId}>
              {isEditing ? "Modifier la recherche" : "Nouvelle recherche enregistrée"}
            </h2>
            <p id={descriptionId}>
              Définissez les critères utilisés lors des prochaines synchronisations.
            </p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Fermer l’éditeur"
            onClick={requestClose}
            disabled={isSubmitting}
          >
            ×
          </button>
        </header>

        <form className="search-editor__form" noValidate onSubmit={handleSubmit}>
          {submitError ? (
            <div className="form-alert" role="alert">
              <strong>Enregistrement impossible</strong>
              <span>{submitError}</span>
            </div>
          ) : null}

          <div className="form-grid form-grid--identity">
            <div className="form-field">
              <label htmlFor="search-name">Nom</label>
              <input
                ref={nameRef}
                id="search-name"
                value={values.name}
                maxLength={200}
                autoComplete="off"
                aria-invalid={Boolean(errors.name)}
                aria-describedby={errors.name ? "search-name-error" : undefined}
                disabled={isSubmitting}
                onChange={(event) => setTextValue("name", event.currentTarget.value)}
              />
              {errors.name ? (
                <p className="field-error" id="search-name-error">
                  {errors.name}
                </p>
              ) : null}
            </div>

            <div className="form-field form-field--wide">
              <label htmlFor="search-keywords">Mots-clés</label>
              <input
                id="search-keywords"
                value={values.keywords}
                autoComplete="off"
                placeholder="backend, python, API"
                aria-invalid={Boolean(errors.keywords)}
                aria-describedby={
                  errors.keywords
                    ? "search-keywords-hint search-keywords-error"
                    : "search-keywords-hint"
                }
                disabled={isSubmitting}
                onChange={(event) =>
                  setTextValue("keywords", event.currentTarget.value)
                }
              />
              <p className="field-hint" id="search-keywords-hint">
                Séparez les termes par une virgule.
              </p>
              {errors.keywords ? (
                <p className="field-error" id="search-keywords-error">
                  {errors.keywords}
                </p>
              ) : null}
            </div>

            <div className="form-field">
              <label htmlFor="search-title">Titre recherché</label>
              <input
                id="search-title"
                value={values.title}
                maxLength={300}
                autoComplete="off"
                placeholder="Développeur backend"
                disabled={isSubmitting}
                onChange={(event) => setTextValue("title", event.currentTarget.value)}
              />
            </div>

            <div className="form-field">
              <label htmlFor="search-location">Lieu</label>
              <input
                id="search-location"
                value={values.location}
                maxLength={300}
                autoComplete="address-level1"
                aria-invalid={Boolean(errors.location)}
                aria-describedby={errors.location ? "search-location-error" : undefined}
                disabled={isSubmitting}
                onChange={(event) =>
                  setTextValue("location", event.currentTarget.value)
                }
              />
              {errors.location ? (
                <p className="field-error" id="search-location-error">
                  {errors.location}
                </p>
              ) : null}
            </div>

            <div className="form-field">
              <label htmlFor="search-radius">Rayon en kilomètres</label>
              <input
                id="search-radius"
                type="number"
                min="1"
                step="1"
                inputMode="numeric"
                value={values.radiusKm}
                placeholder="Sans limite"
                aria-invalid={Boolean(errors.radiusKm)}
                aria-describedby={errors.radiusKm ? "search-radius-error" : undefined}
                disabled={isSubmitting}
                onChange={(event) =>
                  setTextValue("radiusKm", event.currentTarget.value)
                }
              />
              {errors.radiusKm ? (
                <p className="field-error" id="search-radius-error">
                  {errors.radiusKm}
                </p>
              ) : null}
            </div>
          </div>

          <div className="form-separator" />

          <div className="form-grid form-grid--choices">
            <ChoiceGroup
              legend="Types de contrat"
              choices={CONTRACT_CHOICES}
              selected={values.contractTypes}
              disabled={isSubmitting}
              onToggle={(value, checked) =>
                toggleChoice("contractTypes", value, checked)
              }
            />
            <ChoiceGroup
              legend="Organisation du travail"
              choices={WORKPLACE_CHOICES}
              selected={values.workplaceTypes}
              disabled={isSubmitting}
              onToggle={(value, checked) =>
                toggleChoice("workplaceTypes", value, checked)
              }
            />
            <ChoiceGroup
              legend="Niveau d’expérience"
              choices={EXPERIENCE_CHOICES}
              selected={values.experienceLevels}
              disabled={isSubmitting}
              onToggle={(value, checked) =>
                toggleChoice("experienceLevels", value, checked)
              }
            />
          </div>

          <fieldset
            className="choice-group choice-group--sources"
            disabled={isSubmitting}
            aria-invalid={Boolean(errors.sources)}
            aria-describedby={errors.sources ? "search-sources-error" : undefined}
          >
            <legend>Sources</legend>
            <div className="choice-group__items">
              {SOURCE_CHOICES.map((choice) => (
                <label className="choice-chip choice-chip--source" key={choice.value}>
                  <input
                    type="checkbox"
                    checked={values.sources.includes(choice.value)}
                    onChange={(event) =>
                      toggleChoice(
                        "sources",
                        choice.value,
                        event.currentTarget.checked,
                      )
                    }
                  />
                  <span>{choice.label}</span>
                </label>
              ))}
            </div>
            {errors.sources ? (
              <p className="field-error" id="search-sources-error">
                {errors.sources}
              </p>
            ) : null}
          </fieldset>

          <label className="active-toggle">
            <input
              type="checkbox"
              aria-label="Recherche active"
              checked={values.active}
              disabled={isSubmitting}
              onChange={(event) => {
                setValues((current) => ({
                  ...current,
                  active: event.currentTarget.checked,
                }));
              }}
            />
            <span className="active-toggle__control" aria-hidden="true" />
            <span>
              <strong>Recherche active</strong>
              <small>Incluse dans les synchronisations planifiées.</small>
            </span>
          </label>

          <footer className="search-editor__footer">
            <button
              type="button"
              className="button button--quiet"
              onClick={requestClose}
              disabled={isSubmitting}
            >
              Annuler
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={isSubmitting || (isEditing && !hasChanges)}
            >
              {isSubmitting
                ? "Enregistrement en cours…"
                : isEditing
                  ? "Enregistrer les modifications"
                  : "Enregistrer la recherche"}
            </button>
          </footer>
        </form>
      </div>
    </dialog>
  );
}
