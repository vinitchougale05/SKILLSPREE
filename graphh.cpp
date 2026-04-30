#include <iostream>
#include <vector>
using namespace std;

class Graph {
private:
    int vertices;                          // Number of vertices
    vector<vector<int>> adjMatrix;         // 2D vector for adjacency matrix

public:
    // Constructor
    Graph(int v) {
        vertices = v;
        adjMatrix.resize(v, vector<int>(v, 0));
    }

    // Function to add directed edge
    void addEdge(int from, int to) {
        adjMatrix[from][to] = 1;
    }

    // Function to display adjacency matrix
    void display() {
        for (int i = 0; i < vertices; i++) {
            for (int j = 0; j < vertices; j++) {
                cout << adjMatrix[i][j] << " ";
            }
            cout << endl;
        }
    }
};

int main() {
    Graph g(4);          // Create graph with 4 vertices

    g.addEdge(0, 1);     // Edge from 0 → 1
    g.addEdge(0, 2);     // Edge from 0 → 2
    g.addEdge(1, 3);     // Edge from 1 → 3
    g.addEdge(2, 3);     // Edge from 2 → 3

    g.display();         // Print adjacency matrix

    return 0;
}