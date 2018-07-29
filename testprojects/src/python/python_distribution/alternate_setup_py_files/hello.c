#include <Python.h>

static PyObject * hello(PyObject *self, PyObject *args) {
  return Py_BuildValue("s", "hello, world!");
}

static PyMethodDef Methods[] = {
  {"hello", hello, METH_VARARGS, "Yet Another Hello World Implementation."},
  {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC inithello(void) {
  (void) Py_InitModule("hello", Methods);
}
