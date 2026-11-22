// PS4 Store BR Test: aplicativo homebrew MINIMO, so para validar a instalacao ponta a ponta do catalogo.
// Mostra uma tela estatica de confirmacao. Nao acessa rede, arquivos nem dados do usuario.
// Titulo EXPERIMENTAL: o ID CUSA95417 NAO e oficial e nao sera usado em producao.
// Compilado com o OpenOrbis PS4 Toolchain (open source, sem SDK da Sony). Usa Scene2D do toolchain (samples/_common).
#include <stdio.h>
#include <string.h>
#include <sstream>

#include "graphics.h"
#include "log.h"
#include "font5x7.h"

#ifndef APP_VERSION
#define APP_VERSION "1.00"
#endif

#define FRAME_WIDTH  1920
#define FRAME_HEIGHT 1080
#define FRAME_DEPTH  4

std::stringstream debugLogStream;   // exigido por log.h do toolchain

static const Glyph *findGlyph(char c)
{
    for (int i = 0; i < kFontCount; i++)
        if (kFont[i].ch == c) return &kFont[i];
    for (int i = 0; i < kFontCount; i++)      // desconhecido vira espaco
        if (kFont[i].ch == ' ') return &kFont[i];
    return &kFont[0];
}

static int textWidth(const char *s, int scale) { return (int)strlen(s) * 6 * scale - scale; }

static void drawText(Scene2D *scene, const char *s, int x, int y, int scale, Color color)
{
    for (; *s; s++, x += 6 * scale) {
        const Glyph *g = findGlyph(*s);
        for (int row = 0; row < 7; row++)
            for (int col = 0; col < 5; col++)
                if (g->rows[row] & (1 << (4 - col)))
                    scene->DrawRectangle(x + col * scale, y + row * scale, scale, scale, color);
    }
}

static void drawCentered(Scene2D *scene, const char *s, int y, int scale, Color color)
{
    drawText(scene, s, (FRAME_WIDTH - textWidth(s, scale)) / 2, y, scale, color);
}

int main()
{
    setvbuf(stdout, NULL, _IONBF, 0);

    auto scene = new Scene2D(FRAME_WIDTH, FRAME_HEIGHT, FRAME_DEPTH);
    if (!scene->Init(0xC000000, 2)) {
        DEBUGLOG << "Falha ao iniciar a cena 2D";
        for (;;) {}
    }

    const Color bg     = {  8,  40,  24 };
    const Color white  = { 255, 255, 255 };
    const Color green  = { 120, 255, 160 };
    const Color gray   = { 190, 200, 195 };

    int frameID = 0;
    for (;;) {
        scene->FrameBufferFill(bg);
        drawCentered(scene, "PS4 STORE BR TEST", 220, 14, white);
        drawCentered(scene, "INSTALACAO OK", 400, 20, green);
        drawCentered(scene, "TITLE ID: CUSA95417  VERSAO " APP_VERSION, 620, 7, white);
        drawCentered(scene, "CONTENT ID: IV0000-CUSA95417_00-PS4STOREBRTEST00", 700, 5, gray);
        drawCentered(scene, "APLICATIVO EXPERIMENTAL - ID NAO OFICIAL - SO PARA TESTE", 820, 5, gray);
        drawCentered(scene, "APERTE O BOTAO PS PARA SAIR", 940, 6, white);

        scene->SubmitFlip(frameID);
        scene->FrameWait(frameID);
        scene->FrameBufferSwap();
        frameID++;
    }
    return 0;
}
