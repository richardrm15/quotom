"""
Sistema Centralizado de Tema y Estilos (Single Source of Truth visual).

Este módulo es el ÚNICO responsable de la apariencia de la aplicación:

1. Define los tokens de diseño (``ThemeTokens``) para los modos Dark/Light.
2. Carga y parametriza la hoja de estilos ``ui/styles/theme.qss``.
3. Construye el ``QPalette`` nativo sincronizado con el tema activo.
4. Expone iconos vectoriales ya coloreados según el tema activo.
5. Genera los iconos auxiliares (+ / - / chevron) referenciados desde el QSS.

Ninguna vista debe llamar a ``setStyleSheet()``: todo el estilo se centraliza
aquí mediante tokens y selectores de ID/propiedad en ``theme.qss``.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from ui.icons import get_icon

logger = logging.getLogger("quotom.styles")

# Rutas de recursos de estilo
STYLES_DIR: Path = Path(__file__).resolve().parent
QSS_FILE: Path = STYLES_DIR / "theme.qss"


@dataclass(frozen=True)
class ThemeTokens:
    """Conjunto inmutable de tokens de diseño de un tema (Dark o Light)."""

    mode: str

    # Superficies y fondos
    bg_base: str            # Ventana principal
    bg_surface: str         # Barras de herramientas, paneles laterales, status bar
    bg_titlebar: str        # Barra de título personalizada CSD
    bg_canvas: str          # Lienzo del visor detrás de la página PDF
    bg_button: str          # Fondo en reposo de botones
    bg_button_hover: str    # Hover de botones
    bg_input: str           # Fondo de cajas de texto
    bg_input_focus: str     # Fondo de cajas de texto activas
    bg_hover: str           # Hover sutil en items o inputs camuflados

    # Bordes y divisores
    border_base: str        # Bordes sutiles y separadores
    border_hover: str       # Bordes en hover
    border_focus: str       # Borde de foco activo (acento)
    border_titlebar: str    # Borde inferior de la barra de título

    # Tipografía y textos
    text_primary: str       # Texto principal de lectura
    text_secondary: str     # Textos secundarios, muteados y placeholders
    text_disabled: str      # Controles y textos deshabilitados
    text_on_primary: str    # Texto sobre fondo de acento (ej. botones primarios)

    # Acento de marca / primario
    primary: str            # Color de acción primaria (#007ACC)
    primary_hover: str      # Hover del botón primario
    primary_pressed: str    # Pressed del botón primario

    # Iconografía
    icon_default: str       # Color base de trazo de iconos
    icon_hover: str         # Color de trazo en hover
    icon_sun: str           # Acento cálido para icono del sol
    icon_moon: str          # Acento frío para icono de la luna

    # Botones de control de ventana (CSD)
    win_control_hover: str  # Fondo hover para minimizar / maximizar
    win_close_hover: str    # Fondo hover para cerrar ventana (Rojo estándar)

    # Barras de desplazamiento (Scrollbars)
    scroll_track: str       # Fondo del canal
    scroll_handle: str      # Barra de arrastre
    scroll_handle_hover: str

    # Tablas de Cómputo
    table_bg: str
    table_grid: str
    table_header_bg: str
    table_header_text: str
    table_selected_bg: str
    table_selected_text: str

    # Resaltador de búsqueda vectorial
    search_highlight_fill: str
    search_highlight_border: str

    # Paleta de Marcas de Take-Off (contraste WCAG)
    mark_magenta: str
    mark_cyan: str
    mark_orange: str
    mark_lime: str

    # Colores semánticos de estado
    error: str               # Errores, acciones destructivas, contadores sin resultados
    success: str             # Confirmaciones y estados correctos
    warning: str             # Avisos y advertencias (banners, diálogos)


DARK_TOKENS = ThemeTokens(
    mode="dark",
    bg_base="#181818",
    bg_surface="#252526",
    bg_titlebar="#1E1E1E",
    bg_canvas="#0E0E0E",
    bg_button="#2D2D30",
    bg_button_hover="#3E3E42",
    bg_input="#1F1F1F",
    bg_input_focus="#1F1F1F",
    bg_hover="#2A2D2E",

    border_base="#3E3E42",
    border_hover="#4E4E52",
    border_focus="#007ACC",
    border_titlebar="#2D2D30",

    text_primary="#CCCCCC",
    text_secondary="#858585",
    text_disabled="#555555",
    text_on_primary="#FFFFFF",

    primary="#007ACC",
    primary_hover="#0063A6",
    primary_pressed="#00558C",

    icon_default="#CCCCCC",
    icon_hover="#FFFFFF",
    icon_sun="#F59E0B",
    icon_moon="#3B82F6",

    win_control_hover="#3E3E42",
    win_close_hover="#E81123",

    scroll_track="#1E1E1E",
    scroll_handle="#424242",
    scroll_handle_hover="#4F4F4F",

    table_bg="#252526",
    table_grid="#3E3E42",
    table_header_bg="#333333",
    table_header_text="#CCCCCC",
    table_selected_bg="#094771",
    table_selected_text="#FFFFFF",

    search_highlight_fill="rgba(255, 255, 0, 0.40)",
    search_highlight_border="#FFFF00",

    mark_magenta="#EC4899",
    mark_cyan="#06B6D4",
    mark_orange="#F97316",
    mark_lime="#84CC16",

    error="#E06C75",
    success="#98C379",
    warning="#D97706",
)


LIGHT_TOKENS = ThemeTokens(
    mode="light",
    bg_base="#F3F3F3",
    bg_surface="#EAEAEA",
    bg_titlebar="#E6E6E6",
    bg_canvas="#DCDCDC",
    bg_button="#FFFFFF",
    bg_button_hover="#E0E0E0",
    bg_input="#FFFFFF",
    bg_input_focus="#FFFFFF",
    bg_hover="#E0E0E0",

    border_base="#CCCCCC",
    border_hover="#B0B0B0",
    border_focus="#007ACC",
    border_titlebar="#D0D0D0",

    text_primary="#1E1E1E",
    text_secondary="#555555",
    text_disabled="#A0A0A0",
    text_on_primary="#FFFFFF",

    primary="#007ACC",
    primary_hover="#0063A6",
    primary_pressed="#00558C",

    icon_default="#333333",
    icon_hover="#000000",
    icon_sun="#F59E0B",
    icon_moon="#3B82F6",

    win_control_hover="#D6D6D6",
    win_close_hover="#E81123",

    scroll_track="#F0F0F0",
    scroll_handle="#C1C1C1",
    scroll_handle_hover="#A8A8A8",

    table_bg="#FFFFFF",
    table_grid="#E0E0E0",
    table_header_bg="#EAEAEA",
    table_header_text="#1E1E1E",
    table_selected_bg="#CCE8FF",
    table_selected_text="#000000",

    search_highlight_fill="rgba(255, 255, 0, 0.45)",
    search_highlight_border="#EAB308",

    mark_magenta="#EC4899",
    mark_cyan="#06B6D4",
    mark_orange="#F97316",
    mark_lime="#84CC16",

    error="#C0392B",
    success="#2E7D32",
    warning="#B45309",
)


def _ensure_branch_icons(mode: str, tokens: ThemeTokens) -> tuple[str, str, str]:
    """
    Genera en disco los iconos vectoriales [+] / [-] / chevron adaptados al tema.

    Se referencian desde ``theme.qss`` mediante ``image: url(...)`` en las reglas
    del árbol de proyecto y de los desplegables.

    Returns:
        Tupla ``(plus_url, minus_url, chevron_url)`` con rutas POSIX.
    """
    try:
        theme_dir = Path.home() / ".cache" / "quotom" / "theme"
        theme_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        import tempfile

        theme_dir = Path(tempfile.gettempdir()) / "quotom_theme"
        theme_dir.mkdir(parents=True, exist_ok=True)

    p_plus = theme_dir / f"branch_plus_{mode}.png"
    p_minus = theme_dir / f"branch_minus_{mode}.png"
    p_chevron = theme_dir / f"chevron_down_{mode}.png"

    try:
        for is_plus, path in ((True, p_plus), (False, p_minus)):
            size = 12
            pix = QPixmap(size, size)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Cajita redondeada sutil
            painter.setPen(QPen(QColor(tokens.text_secondary), 1.0))
            painter.setBrush(QColor(tokens.bg_surface))
            painter.drawRoundedRect(QRectF(1.0, 1.0, size - 2.0, size - 2.0), 2.0, 2.0)

            # Trazo horizontal (-)
            half = size / 2.0
            painter.setPen(
                QPen(
                    QColor(tokens.text_primary),
                    1.2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                )
            )
            painter.drawLine(3.0, half, size - 3.0, half)

            # Trazo vertical (+) si es estado colapsado
            if is_plus:
                painter.drawLine(half, 3.0, half, size - 3.0)

            painter.end()
            pix.save(str(path))

        # Chevron down para desplegables (QComboBox)
        pix_c = QPixmap(12, 12)
        pix_c.fill(Qt.GlobalColor.transparent)
        painter_c = QPainter(pix_c)
        painter_c.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter_c.setPen(
            QPen(
                QColor(tokens.text_secondary),
                1.5,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        painter_c.drawLine(QPointF(2.5, 4.5), QPointF(6.0, 8.0))
        painter_c.drawLine(QPointF(6.0, 8.0), QPointF(9.5, 4.5))
        painter_c.end()
        pix_c.save(str(p_chevron))
    except Exception as exc:  # pragma: no cover - generación best-effort
        logger.warning("No se pudieron generar los iconos de rama del QSS: %s", exc)

    return p_plus.as_posix(), p_minus.as_posix(), p_chevron.as_posix()


def _load_qss_template() -> str:
    """Lee la plantilla QSS centralizada (``ui/styles/theme.qss``)."""
    try:
        return QSS_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("No se pudo leer la hoja de estilos %s: %s", QSS_FILE, exc)
        return ""


def build_qss(tokens: ThemeTokens, mode: str) -> str:
    """
    Parametriza ``theme.qss`` sustituyendo los marcadores por los tokens del tema.

    Args:
        tokens: Tokens de diseño del tema activo.
        mode: Identificador del modo (``"dark"`` / ``"light"``), usado para las
            rutas de los iconos auxiliares.

    Returns:
        La hoja de estilos lista para ``QApplication.setStyleSheet()``.
    """
    template = _load_qss_template()
    if not template:
        return ""

    plus_url, minus_url, chevron_url = _ensure_branch_icons(mode, tokens)
    values = asdict(tokens)
    values.update(plus_url=plus_url, minus_url=minus_url, chevron_url=chevron_url)

    try:
        return template.format(**values)
    except (KeyError, IndexError) as exc:
        logger.error("Marcador de tema desconocido en theme.qss: %s", exc)
        return ""


class ThemeManager:
    """
    Fachada central del sistema de diseño.

    Provee métodos desacoplados para aplicar temas, obtener tokens, paletas
    nativas, colores específicos e iconos reactivos al tema activo.
    """

    _current_mode: str = "dark"
    _tokens_map: dict[str, ThemeTokens] = {
        "dark": DARK_TOKENS,
        "light": LIGHT_TOKENS,
    }

    # ------------------------------------------------------------------ Tokens

    @classmethod
    def current_mode(cls) -> str:
        """Devuelve el identificador del modo activo (``dark`` / ``light``)."""
        return cls._current_mode

    @classmethod
    def tokens(cls) -> ThemeTokens:
        """Devuelve los tokens de diseño del tema activo."""
        return cls._tokens_map[cls._current_mode]

    @classmethod
    def color(cls, token_name: str) -> QColor:
        """Devuelve un ``QColor`` tipado a partir del nombre de un token."""
        value = getattr(cls.tokens(), token_name, None)
        return QColor(value) if value is not None else QColor()

    @classmethod
    def canvas_background_color(cls) -> str:
        """Color de fondo del lienzo detrás de la página PDF."""
        return cls.tokens().bg_canvas

    @classmethod
    def get_icon(cls, name: str, size: int = 20, color: str | None = None) -> QIcon:
        """
        Icono vectorial nativo con el color de trazo exacto del tema activo.

        Args:
            name: Nombre del icono en la fábrica (``ui/icons``).
            size: Lado en píxeles.
            color: Color explícito para teñirlo (p. ej. el token ``warning`` en un
                banner de aviso). Si es ``None`` se usa el color del tema.
        """
        tok = cls.tokens()
        if color:
            color_hex = color
        elif name == "sun":
            color_hex = tok.icon_sun
        elif name == "moon":
            color_hex = tok.icon_moon
        else:
            color_hex = tok.icon_default
        return get_icon(name, color_hex=color_hex, size=size)

    @classmethod
    def mark_palette(cls) -> dict[str, str]:
        """Catálogo de colores contrastados para las marcas de Take-Off."""
        tok = cls.tokens()
        return {
            "E-LUM": tok.mark_magenta,
            "E-TAB": tok.mark_cyan,
            "FA-DET": tok.mark_orange,
            "M-VAL": tok.mark_lime,
        }

    # ------------------------------------------------------------------ Paleta

    @classmethod
    def palette(cls) -> QPalette:
        """Construye el ``QPalette`` nativo a partir de los tokens actuales."""
        tok = cls.tokens()
        pal = QPalette()
        pal.setColor(QPalette.ColorRole.Window, QColor(tok.bg_base))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(tok.text_primary))
        pal.setColor(QPalette.ColorRole.Base, QColor(tok.bg_input))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor(tok.bg_surface))
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(tok.bg_surface))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor(tok.text_primary))
        pal.setColor(QPalette.ColorRole.Text, QColor(tok.text_primary))
        pal.setColor(QPalette.ColorRole.Button, QColor(tok.bg_button))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(tok.text_primary))
        pal.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.white)
        pal.setColor(QPalette.ColorRole.Highlight, QColor(tok.primary))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor(tok.text_on_primary))
        return pal

    # ------------------------------------------------------------------- Tema

    @classmethod
    def apply_theme_to_app(cls, app: QApplication, mode: str = "dark") -> None:
        """
        Aplica el tema indicado a una instancia concreta de ``QApplication``.

        Método explícito (sin depender de ``QApplication.instance()``) para poder
        ser invocado desde un controlador con la dependencia inyectada.
        """
        normalized = mode.lower()
        cls._current_mode = normalized if normalized in cls._tokens_map else "dark"

        tok = cls.tokens()
        hints = app.styleHints()
        if hasattr(hints, "setColorScheme"):
            hints.setColorScheme(
                Qt.ColorScheme.Light
                if cls._current_mode == "light"
                else Qt.ColorScheme.Dark
            )

        app.setPalette(cls.palette())
        app.setStyleSheet(build_qss(tok, mode=cls._current_mode))
        logger.info("Tema '%s' aplicado.", cls._current_mode)

    @classmethod
    def apply_theme(cls, mode: str = "dark") -> None:
        """Aplica el tema globalmente usando la ``QApplication`` activa."""
        app = QApplication.instance()
        if not app:
            return
        cls.apply_theme_to_app(app, mode)

    @classmethod
    def toggle_theme(cls) -> str:
        """Alterna claro/oscuro, aplicándolo y devolviendo el nuevo modo."""
        new_mode = "light" if cls._current_mode == "dark" else "dark"
        cls.apply_theme(new_mode)
        return new_mode

    # -------------------------------------------------------- Estilos derivados

    @classmethod
    def apply_zone_color(cls, widget, color_hex: str) -> None:
        """
        Tiñe un widget con el color de una zona del auto-nombrador.

        El color es un **dato** (lo elige el usuario para cada zona) y no
        vocabulario del tema, así que no puede vivir en ``theme.qss``. Se
        centraliza aquí para que la vista no conozca QSS (Regla 18); el resto del
        aspecto del widget (radio, padding, tamaño) sigue en ``theme.qss``.
        """
        widget.setStyleSheet(
            f"background-color: {color_hex}; color: #FFFFFF; font-weight: bold;"
        )

    @classmethod
    def apply_inline_editor_style(cls, editor, text_color: str, background: str) -> None:
        """
        Aplica el estilo del editor de texto en línea de las anotaciones.

        Vive aquí y **no** en ``theme.qss`` porque parte de sus valores son
        **datos** de la anotación (el color de texto que eligió el usuario y el
        fondo de contraste calculado a partir de su luminancia), no vocabulario
        del tema. Centralizarlo aquí evita que la vista conozca QSS (Regla 18).
        """
        editor.setObjectName("annotationTextEditor")
        editor.setStyleSheet(
            f"""
            QTextEdit#annotationTextEditor {{
                background-color: {background};
                color: {text_color};
                border: 2px solid {cls.tokens().primary};
                border-radius: 4px;
                padding: 3px 5px;
            }}
            """
        )


__all__ = [
    "ThemeTokens",
    "DARK_TOKENS",
    "LIGHT_TOKENS",
    "ThemeManager",
    "build_qss",
    "STYLES_DIR",
    "QSS_FILE",
]
