/*
 * train_fast.c - Fast N-tuple network trainer for 2048
 *
 * Standalone C program that trains the same N-tuple network as train_ntuple.py
 * but 50-100x faster. Uses TD(0) afterstate learning.
 *
 * Compile (MSYS2/MinGW):
 *   gcc -O3 -o train_fast.exe train_fast.c -lm
 *
 * Usage:
 *   train_fast.exe [n_games] [learning_rate] [weights_file]
 *   train_fast.exe 500000              # 500K games, default lr
 *   train_fast.exe 500000 0.001        # custom lr
 *   train_fast.exe 500000 0.001 ntuple_weights.bin
 *
 * After training, convert weights to Python format:
 *   python convert_weights.py ntuple_weights.bin ntuple_weights.npz
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

/* ------------------------------------------------------------------ */
/* Constants                                                           */
/* ------------------------------------------------------------------ */

#define GRID 4
#define BOARD_SIZE 16
#define N_TILE_VALUES 16
#define MAX_PATTERNS 20
#define MAX_EXPANDED 100
#define MAX_CELLS_PER_PATTERN 6

/* ------------------------------------------------------------------ */
/* Board representation                                                */
/* ------------------------------------------------------------------ */

/* Board is 16 cells, each stores log2(tile): 0=empty, 1=2, 2=4, ... 15=32768 */
typedef unsigned char Cell;
typedef Cell Board[BOARD_SIZE];

static inline Cell tile_to_index(int tile_value) {
    if (tile_value == 0) return 0;
    Cell idx = 0;
    int v = tile_value;
    while (v > 1) { v >>= 1; idx++; }
    return idx < N_TILE_VALUES ? idx : N_TILE_VALUES - 1;
}

static inline int index_to_tile(Cell idx) {
    if (idx == 0) return 0;
    return 1 << idx;
}

#define CELL(b, r, c) ((b)[(r) * GRID + (c)])

/* ------------------------------------------------------------------ */
/* N-tuple patterns (must match ntuple_network.py PATTERNS)            */
/* ------------------------------------------------------------------ */

typedef struct {
    int cells[MAX_CELLS_PER_PATTERN]; /* flat indices into board (r*4+c) */
    int n_cells;
    int table_idx;                    /* which weight table */
} Pattern;

/* Base patterns from ntuple_network.py */
static const int BASE_PATTERNS[][MAX_CELLS_PER_PATTERN] = {
    /* 5-tuples (r*4+c) */
    {0,1,2,3,4},       /* (0,0)(0,1)(0,2)(0,3)(1,0) */
    {0,1,4,5,8},       /* (0,0)(0,1)(1,0)(1,1)(2,0) */
    {0,1,2,4,5},       /* (0,0)(0,1)(0,2)(1,0)(1,1) */
    {0,4,8,12,1},      /* (0,0)(1,0)(2,0)(3,0)(0,1) */
    /* 4-tuples */
    {0,1,2,3},         /* full row */
    {4,5,6,7},         /* full row */
    {0,4,8,12},        /* full column */
    {0,1,4,5},         /* 2x2 */
    {1,2,5,6},         /* 2x2 */
    {4,5,8,9},         /* 2x2 */
    {0,1,5,6},         /* Z-shape */
};
static const int BASE_PATTERN_SIZES[] = {5,5,5,5, 4,4,4,4,4,4,4};
#define N_BASE_PATTERNS 11

/* Symmetry operations on 4x4 grid */
static inline int rotate90(int idx) {
    int r = idx / 4, c = idx % 4;
    return c * 4 + (3 - r);
}

static inline int reflect_h(int idx) {
    int r = idx / 4, c = idx % 4;
    return r * 4 + (3 - c);
}

/* Global network */
static float *weight_tables[MAX_PATTERNS];
static int table_sizes[MAX_PATTERNS];
static int n_tables = 0;
static Pattern expanded[MAX_EXPANDED];
static int n_expanded = 0;

static void transform_pattern(const int *src, int n, int *dst,
                              int (*fn)(int)) {
    for (int i = 0; i < n; i++) dst[i] = fn(src[i]);
}

static int pattern_key(const int *cells, int n) {
    /* Sort a copy to get canonical form */
    int sorted[MAX_CELLS_PER_PATTERN];
    memcpy(sorted, cells, n * sizeof(int));
    for (int i = 0; i < n-1; i++)
        for (int j = i+1; j < n; j++)
            if (sorted[i] > sorted[j]) {
                int t = sorted[i]; sorted[i] = sorted[j]; sorted[j] = t;
            }
    int key = 0;
    for (int i = 0; i < n; i++) key = key * 17 + sorted[i];
    return key;
}

static void init_network(void) {
    /* For each base pattern, generate all 8 symmetries */
    int seen_keys[1000];
    int n_seen;

    for (int p = 0; p < N_BASE_PATTERNS; p++) {
        int n = BASE_PATTERN_SIZES[p];
        int size = 1;
        for (int i = 0; i < n; i++) size *= N_TILE_VALUES;
        table_sizes[p] = size;
        weight_tables[p] = (float *)calloc(size, sizeof(float));
        if (!weight_tables[p]) {
            fprintf(stderr, "Failed to allocate weight table %d (%d entries)\n", p, size);
            exit(1);
        }

        n_seen = 0;
        int current[MAX_CELLS_PER_PATTERN];
        memcpy(current, BASE_PATTERNS[p], n * sizeof(int));

        for (int rot = 0; rot < 4; rot++) {
            /* Check if this orientation is new */
            int key = pattern_key(current, n);
            int dup = 0;
            for (int s = 0; s < n_seen; s++)
                if (seen_keys[s] == key) { dup = 1; break; }
            if (!dup) {
                seen_keys[n_seen++] = key;
                Pattern *pat = &expanded[n_expanded++];
                pat->table_idx = p;
                pat->n_cells = n;
                memcpy(pat->cells, current, n * sizeof(int));
            }

            /* Reflected version */
            int reflected[MAX_CELLS_PER_PATTERN];
            transform_pattern(current, n, reflected, reflect_h);
            key = pattern_key(reflected, n);
            dup = 0;
            for (int s = 0; s < n_seen; s++)
                if (seen_keys[s] == key) { dup = 1; break; }
            if (!dup) {
                seen_keys[n_seen++] = key;
                Pattern *pat = &expanded[n_expanded++];
                pat->table_idx = p;
                pat->n_cells = n;
                memcpy(pat->cells, reflected, n * sizeof(int));
            }

            /* Rotate for next iteration */
            int rotated[MAX_CELLS_PER_PATTERN];
            transform_pattern(current, n, rotated, rotate90);
            memcpy(current, rotated, n * sizeof(int));
        }
    }
    n_tables = N_BASE_PATTERNS;
}

/* ------------------------------------------------------------------ */
/* Network evaluate / update                                           */
/* ------------------------------------------------------------------ */

static inline int feature_index(const Board b, const Pattern *pat) {
    int idx = 0;
    for (int i = 0; i < pat->n_cells; i++)
        idx = idx * N_TILE_VALUES + b[pat->cells[i]];
    return idx;
}

static float evaluate(const Board b) {
    float total = 0.0f;
    for (int i = 0; i < n_expanded; i++)
        total += weight_tables[expanded[i].table_idx][feature_index(b, &expanded[i])];
    return total;
}

static void update_weights(const Board b, float delta) {
    for (int i = 0; i < n_expanded; i++)
        weight_tables[expanded[i].table_idx][feature_index(b, &expanded[i])] += delta;
}

/* ------------------------------------------------------------------ */
/* 2048 game engine                                                    */
/* ------------------------------------------------------------------ */

/* Row move lookup table: row(4 cells) -> result(4 cells) + score */
typedef struct { Cell cells[4]; int score; } RowResult;

/* 16^4 = 65536 possible rows */
static RowResult row_left_table[65536];
static int row_table_built = 0;

static int row_to_key(Cell a, Cell b, Cell c, Cell d) {
    return (a << 12) | (b << 8) | (c << 4) | d;
}

static void build_row_table(void) {
    for (int key = 0; key < 65536; key++) {
        Cell cells[4] = {
            (key >> 12) & 0xF,
            (key >> 8) & 0xF,
            (key >> 4) & 0xF,
            key & 0xF
        };

        /* Compress left with merging */
        Cell packed[4] = {0,0,0,0};
        int n = 0;
        for (int i = 0; i < 4; i++)
            if (cells[i]) packed[n++] = cells[i];

        Cell out[4] = {0,0,0,0};
        int score = 0, j = 0;
        for (int i = 0; i < n; ) {
            if (i + 1 < n && packed[i] == packed[i+1]) {
                Cell merged = packed[i] + 1; /* log2 space: merge = increment */
                out[j++] = merged;
                score += index_to_tile(merged);
                i += 2;
            } else {
                out[j++] = packed[i];
                i++;
            }
        }

        RowResult *r = &row_left_table[key];
        memcpy(r->cells, out, 4);
        r->score = score;
    }
    row_table_built = 1;
}

static inline int move_row_left(const Cell *in, Cell *out) {
    int key = row_to_key(in[0], in[1], in[2], in[3]);
    RowResult *r = &row_left_table[key];
    memcpy(out, r->cells, 4);
    return r->score;
}

static inline int move_row_right(const Cell *in, Cell *out) {
    int key = row_to_key(in[3], in[2], in[1], in[0]);
    RowResult *r = &row_left_table[key];
    out[3] = r->cells[0]; out[2] = r->cells[1];
    out[1] = r->cells[2]; out[0] = r->cells[3];
    return r->score;
}

/* Returns score gained from merges. out must be different from in. */
static int do_move(const Board in, Board out, int dir) {
    int score = 0;
    switch (dir) {
    case 0: /* left */
        for (int r = 0; r < 4; r++)
            score += move_row_left(&in[r*4], &out[r*4]);
        break;
    case 1: /* right */
        for (int r = 0; r < 4; r++)
            score += move_row_right(&in[r*4], &out[r*4]);
        break;
    case 2: /* up */
        for (int c = 0; c < 4; c++) {
            Cell col_in[4] = {in[c], in[4+c], in[8+c], in[12+c]};
            Cell col_out[4];
            score += move_row_left(col_in, col_out);
            out[c] = col_out[0]; out[4+c] = col_out[1];
            out[8+c] = col_out[2]; out[12+c] = col_out[3];
        }
        break;
    case 3: /* down */
        for (int c = 0; c < 4; c++) {
            Cell col_in[4] = {in[c], in[4+c], in[8+c], in[12+c]};
            Cell col_out[4];
            score += move_row_right(col_in, col_out);
            out[c] = col_out[0]; out[4+c] = col_out[1];
            out[8+c] = col_out[2]; out[12+c] = col_out[3];
        }
        break;
    }
    return score;
}

static int boards_equal(const Board a, const Board b) {
    return memcmp(a, b, BOARD_SIZE) == 0;
}

static int count_empty(const Board b) {
    int n = 0;
    for (int i = 0; i < BOARD_SIZE; i++)
        if (b[i] == 0) n++;
    return n;
}

/* Fast RNG (xorshift64) */
static unsigned long long rng_state = 0;

static unsigned long long xorshift64(void) {
    unsigned long long x = rng_state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    rng_state = x;
    return x;
}

static void spawn_tile(Board b) {
    int empties[BOARD_SIZE], n = 0;
    for (int i = 0; i < BOARD_SIZE; i++)
        if (b[i] == 0) empties[n++] = i;
    if (n == 0) return;
    int pos = empties[xorshift64() % n];
    b[pos] = (xorshift64() % 10 < 9) ? 1 : 2; /* 90% tile-2, 10% tile-4 */
}

static int max_tile_index(const Board b) {
    int mx = 0;
    for (int i = 0; i < BOARD_SIZE; i++)
        if (b[i] > mx) mx = b[i];
    return mx;
}

/* ------------------------------------------------------------------ */
/* Training                                                            */
/* ------------------------------------------------------------------ */

typedef struct {
    Board afterstate;
    int move_score;
} BestMove;

static BestMove find_best_move(const Board board) {
    BestMove best;
    best.move_score = -1; /* sentinel: no valid move */
    float best_value = -1e30f;
    Board nb;

    for (int dir = 0; dir < 4; dir++) {
        int score = do_move(board, nb, dir);
        if (boards_equal(board, nb)) continue;

        float value = evaluate(nb) + (float)score;
        if (value > best_value) {
            best_value = value;
            memcpy(best.afterstate, nb, BOARD_SIZE);
            best.move_score = score;
        }
    }
    return best;
}

static void play_game(float lr, int *out_max_tile, int *out_score, int *out_moves) {
    Board board;
    memset(board, 0, BOARD_SIZE);
    spawn_tile(board);
    spawn_tile(board);

    int total_score = 0, n_moves = 0;

    while (1) {
        BestMove bm = find_best_move(board);
        if (bm.move_score < 0) break; /* game over */

        total_score += bm.move_score;
        n_moves++;

        float v_current = evaluate(bm.afterstate);

        /* Spawn random tile */
        memcpy(board, bm.afterstate, BOARD_SIZE);
        spawn_tile(board);

        /* Find next afterstate */
        BestMove next = find_best_move(board);
        float td_error;
        if (next.move_score >= 0) {
            float v_next = evaluate(next.afterstate) + (float)next.move_score;
            td_error = v_next - v_current;
        } else {
            td_error = -v_current;
        }

        /* Update */
        float delta = lr * td_error / n_expanded;
        update_weights(bm.afterstate, delta);

        if (next.move_score < 0) break;
    }

    *out_max_tile = index_to_tile(max_tile_index(board));
    *out_score = total_score;
    *out_moves = n_moves;
}

/* ------------------------------------------------------------------ */
/* Weight I/O (simple binary format)                                   */
/* ------------------------------------------------------------------ */

static int save_weights(const char *path) {
    FILE *f = fopen(path, "wb");
    if (!f) return 0;

    /* Header: magic + n_tables */
    int magic = 0x4E545550; /* "NTUP" */
    fwrite(&magic, 4, 1, f);
    fwrite(&n_tables, 4, 1, f);

    for (int i = 0; i < n_tables; i++) {
        fwrite(&table_sizes[i], 4, 1, f);
        fwrite(weight_tables[i], sizeof(float), table_sizes[i], f);
    }
    fclose(f);
    return 1;
}

static int load_weights(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;

    int magic, nt;
    fread(&magic, 4, 1, f);
    if (magic != 0x4E545550) { fclose(f); return 0; }
    fread(&nt, 4, 1, f);
    if (nt != n_tables) { fclose(f); return 0; }

    for (int i = 0; i < n_tables; i++) {
        int size;
        fread(&size, 4, 1, f);
        if (size != table_sizes[i]) { fclose(f); return 0; }
        fread(weight_tables[i], sizeof(float), size, f);
    }
    fclose(f);
    return 1;
}

/* ------------------------------------------------------------------ */
/* Main                                                                */
/* ------------------------------------------------------------------ */

int main(int argc, char **argv) {
    int n_games = 500000;
    float lr = 0.0025f;
    const char *weights_file = "ntuple_weights.bin";
    int save_every = 10000;
    int stats_every = 1000;

    if (argc > 1) n_games = atoi(argv[1]);
    if (argc > 2) lr = (float)atof(argv[2]);
    if (argc > 3) weights_file = argv[3];

    /* Seed RNG */
    rng_state = (unsigned long long)time(NULL) ^ 0xDEADBEEFULL;

    /* Init */
    build_row_table();
    init_network();

    printf("N-tuple fast trainer (C)\n");
    printf("Patterns: %d, Expanded: %d\n", n_tables, n_expanded);
    {
        long long total = 0;
        for (int i = 0; i < n_tables; i++) total += table_sizes[i];
        printf("Total weights: %lld (%.1f MB)\n", total, total * 4.0 / (1024*1024));
    }

    /* Try loading existing weights */
    if (load_weights(weights_file))
        printf("Resumed from %s\n", weights_file);
    else
        printf("Starting fresh training\n");

    printf("Training %d games, lr=%.4f, saving every %d\n\n", n_games, lr, save_every);

    /* Stats tracking */
    int interval_scores = 0, interval_max_sum = 0, interval_best = 0;
    int count_2048 = 0, count_4096 = 0, count_8192 = 0, count_16384 = 0;
    clock_t interval_start = clock();
    clock_t total_start = clock();

    for (int g = 1; g <= n_games; g++) {
        int mt, score, moves;
        play_game(lr, &mt, &score, &moves);

        interval_scores += score;
        interval_max_sum += mt;
        if (mt > interval_best) interval_best = mt;
        if (mt >= 2048)  count_2048++;
        if (mt >= 4096)  count_4096++;
        if (mt >= 8192)  count_8192++;
        if (mt >= 16384) count_16384++;

        if (g % stats_every == 0) {
            clock_t now = clock();
            double elapsed = (double)(now - interval_start) / CLOCKS_PER_SEC;
            double total_elapsed = (double)(now - total_start) / CLOCKS_PER_SEC;
            double gps = stats_every / elapsed;

            printf("Game %7d | avg_score %8d | avg_max %6d | best %5d | "
                   "2048+ %3d/%d | 4096+ %3d/%d | 8192+ %3d/%d | "
                   "%.0f g/s | %.0fm\n",
                   g,
                   interval_scores / stats_every,
                   interval_max_sum / stats_every,
                   interval_best,
                   count_2048, stats_every,
                   count_4096, stats_every,
                   count_8192, stats_every,
                   gps, total_elapsed / 60.0);

            interval_scores = 0;
            interval_max_sum = 0;
            interval_best = 0;
            count_2048 = count_4096 = count_8192 = count_16384 = 0;
            interval_start = clock();
        }

        if (g % save_every == 0) {
            save_weights(weights_file);
            printf("  -> Saved to %s\n", weights_file);
        }
    }

    save_weights(weights_file);
    double total_time = (double)(clock() - total_start) / CLOCKS_PER_SEC;
    printf("\nDone. %d games in %.1f minutes (%.1f hours)\n",
           n_games, total_time / 60.0, total_time / 3600.0);
    printf("Weights saved to %s\n", weights_file);
    printf("Convert to Python: python convert_weights.py %s ntuple_weights.npz\n",
           weights_file);

    /* Cleanup */
    for (int i = 0; i < n_tables; i++) free(weight_tables[i]);
    return 0;
}
