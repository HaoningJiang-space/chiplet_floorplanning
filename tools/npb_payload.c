/* Count only NPB 3.4.3 IS key redistributions and DT feature arrays. */
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>

enum { ranks = 16 };
static unsigned long long sent[ranks], received[ranks];
static int redistributions;

static void world_order(MPI_Comm comm) {
    int size, comparison;
    PMPI_Comm_size(comm, &size);
    PMPI_Comm_compare(comm, MPI_COMM_WORLD, &comparison);
    if (size != ranks || (comparison != MPI_IDENT && comparison != MPI_CONGRUENT))
        PMPI_Abort(MPI_COMM_WORLD, 2);
}

int MPI_Send(const void *buf, int count, MPI_Datatype type, int dest,
             int tag, MPI_Comm comm) {
    int rc = PMPI_Send(buf, count, type, dest, tag, comm);
    if (rc == MPI_SUCCESS && type == MPI_DOUBLE && count > 1) {
        int bytes;
        world_order(comm);
        PMPI_Type_size(type, &bytes);
        sent[dest] += (unsigned long long) count * bytes;
    }
    return rc;
}

int MPI_Recv(void *buf, int count, MPI_Datatype type, int source,
             int tag, MPI_Comm comm, MPI_Status *status) {
    MPI_Status local;
    MPI_Status *actual = status == MPI_STATUS_IGNORE ? &local : status;
    int rc = PMPI_Recv(buf, count, type, source, tag, comm, actual);
    if (rc == MPI_SUCCESS && type == MPI_DOUBLE) {
        int n, bytes;
        PMPI_Get_count(actual, type, &n);
        if (n > 1) {
            world_order(comm);
            PMPI_Type_size(type, &bytes);
            received[actual->MPI_SOURCE] += (unsigned long long) n * bytes;
        }
    }
    return rc;
}

int MPI_Alltoallv(const void *s, const int *sc, const int *sd, MPI_Datatype st,
                  void *r, const int *rc, const int *rd, MPI_Datatype rt, MPI_Comm comm) {
    int code = PMPI_Alltoallv(s, sc, sd, st, r, rc, rd, rt, comm);
    if (code == MPI_SUCCESS && ++redistributions > 1) {
        int sb, rb;
        world_order(comm);
        PMPI_Type_size(st, &sb);
        PMPI_Type_size(rt, &rb);
        for (int i = 0; i < ranks; ++i) {
            sent[i] += (unsigned long long) sc[i] * sb;
            received[i] += (unsigned long long) rc[i] * rb;
        }
    }
    return code;
}

int MPI_Finalize(void) {
    char filename[4096];
    int me;
    world_order(MPI_COMM_WORLD);
    PMPI_Comm_rank(MPI_COMM_WORLD, &me);
    const char *dir = getenv("NPB_TRACE_DIR");
    if (!dir || snprintf(filename, sizeof(filename), "%s/rank-%d.txt", dir, me) >= (int) sizeof(filename))
        PMPI_Abort(MPI_COMM_WORLD, 3);
    FILE *file = fopen(filename, "wx");
    if (!file) PMPI_Abort(MPI_COMM_WORLD, 4);
    fprintf(file, "%d\n", redistributions);
    for (int i = 0; i < ranks; ++i)
        fprintf(file, "%llu %llu\n", sent[i], received[i]);
    if (fclose(file) != 0) PMPI_Abort(MPI_COMM_WORLD, 5);
    return PMPI_Finalize();
}
